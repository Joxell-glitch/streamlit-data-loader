from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx
import websockets
from websockets.client import WebSocketClientProtocol

from src.config.models import APISettings
from src.core.logging import get_logger

logger = get_logger(__name__)


class HyperliquidClient:
    """Thin wrapper around Hyperliquid REST and WebSocket APIs."""

    def __init__(self, api_settings: APISettings, network: str = "mainnet") -> None:
        self.api_settings = api_settings
        self.network = network
        self._ws: Optional[WebSocketClientProtocol] = None
        self._ws_lock = asyncio.Lock()
        self._session = httpx.AsyncClient(timeout=10.0)
        self._connected_event = asyncio.Event()
        # Market data caches
        self._orderbooks_spot: Dict[str, Dict[str, Any]] = {}
        self._orderbooks_perp: Dict[str, Dict[str, Any]] = {}
        self._marks: Dict[str, float] = {}
        self._mids_map: Dict[str, float] = {}
        self._spot_symbol_to_base: Dict[str, str] = {}
        self._perp_symbol_to_base: Dict[str, str] = {}
        self._mark_symbol_to_base: Dict[str, str] = {}

        # Tracking assets
        self._tracked_bases: set[str] = set()

        # Subscriptions/bookkeeping
        self._orderbook_listeners: List[Callable[[str, str, Dict[str, Any]], None]] = []
        self._mark_listeners: List[Callable[[str, float, Dict[str, Any]], None]] = []
        self._recv_task: Optional[asyncio.Task] = None
        self._spot_subscriptions: set[str] = set()
        self._perp_subscriptions: set[str] = set()
        self._mark_subscriptions: set[str] = set()
        self._sent_subscriptions: set[tuple] = set()
        self._all_mids_subscribed = False
        self._raw_sample_logged = 0
        self._first_market_logged = False
        self._first_data_logged = False
        self._first_l2book_logged = False
        self._first_allmids_logged = False
        self._first_data_event = asyncio.Event()

    @property
    def rest_base(self) -> str:
        return self.api_settings.rest_base if self.network == "mainnet" else self.api_settings.testnet_rest_base

    @property
    def websocket_url(self) -> str:
        return self.api_settings.websocket_url if self.network == "mainnet" else self.api_settings.testnet_websocket_url

    async def fetch_info(self) -> Dict[str, Any]:
        url = f"{self.rest_base}{self.api_settings.info_path}"
        resp = await self._session.post(url, json={"type": "info"})
        resp.raise_for_status()
        return resp.json()

    async def fetch_spot_meta(self) -> Dict[str, Any]:
        url = f"{self.rest_base}{self.api_settings.info_path}"
        resp = await self._session.post(url, json={"type": "spotMeta"})
        resp.raise_for_status()
        return resp.json()

    async def fetch_orderbook_snapshot(self, coin: str) -> Dict[str, Any]:
        url = f"{self.rest_base}{self.api_settings.info_path}"
        resp = await self._session.post(url, json={"type": "l2Book", "coin": coin})
        resp.raise_for_status()
        return resp.json()

    # Listener registration -------------------------------------------------

    def add_orderbook_listener(self, cb: Callable[[str, str, Dict[str, Any]], None]) -> None:
        self._orderbook_listeners.append(cb)

    def add_mark_listener(self, cb: Callable[[str, float, Dict[str, Any]], None]) -> None:
        self._mark_listeners.append(cb)

    # WebSocket lifecycle ---------------------------------------------------

    async def connect_ws(self) -> None:
        async with self._ws_lock:
            if self._ws and not self._ws.closed:
                return
            backoff = 1
            while True:
                try:
                    logger.info("Connecting to Hyperliquid WebSocket: %s", self.websocket_url)
                    self._ws = await websockets.connect(self.websocket_url, ping_interval=20)
                    self._connected_event.set()
                    logger.info("WebSocket connected")
                    return
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("WebSocket connection failed: %s", exc)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

    async def subscribe_orderbooks(self, symbol_map: Dict[str, str], kind: str = "spot") -> None:
        await self._connected_event.wait()
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        for coin, base in symbol_map.items():
            sub_payload: Dict[str, Any] = {"type": "l2Book", "coin": coin}
            sub_key = ("l2Book", coin, kind)
            perp_key = f"perp:{coin}"
            spot_key = f"spot:{coin}"
            if kind == "perp":
                sub_payload["isPerp"] = True
                self._perp_subscriptions.add(perp_key)
                self._perp_symbol_to_base[coin] = base
            else:
                self._spot_subscriptions.add(spot_key)
                self._spot_symbol_to_base[coin] = base
            if sub_key in self._sent_subscriptions:
                continue
            await self._send_subscribe(sub_payload)
            self._sent_subscriptions.add(sub_key)
            await asyncio.sleep(0.2)

    async def subscribe_mark_prices(self, symbol_map: Dict[str, str]) -> None:
        await self._connected_event.wait()
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        for coin, base in symbol_map.items():
            if coin in self._mark_subscriptions:
                continue
            self._mark_subscriptions.add(coin)
            self._mark_symbol_to_base[coin] = base
            await self._send_subscribe({"type": "markPrice", "coin": coin})
            await asyncio.sleep(0.2)

    async def start_market_data(
        self,
        coins_spot: Iterable[str],
        coins_perp: Iterable[str],
        coins_mark: Iterable[str],
    ) -> None:
        coins_spot_list = list(coins_spot)
        coins_perp_list = list(coins_perp)
        coins_mark_list = list(coins_mark)
        self._tracked_bases.update(coins_spot_list)
        self._tracked_bases.update(coins_perp_list)
        self._tracked_bases.update(coins_mark_list)
        spot_symbols = {self._normalize_spot_symbol(base): base for base in coins_spot_list}
        perp_symbols = {self._normalize_perp_symbol(base): base for base in coins_perp_list}
        mark_symbols = {self._normalize_perp_symbol(base): base for base in coins_mark_list}
        await self.connect_ws()
        if not self._recv_task or self._recv_task.done():
            self._recv_task = asyncio.create_task(self._ws_recv_loop())
        await self.subscribe_mark_prices(mark_symbols)
        await self.subscribe_orderbooks(spot_symbols, kind="spot")
        await self.subscribe_orderbooks(perp_symbols, kind="perp")

    async def _ws_recv_loop(self) -> None:
        sample_limit = 5
        while True:
            await self._connected_event.wait()
            if not self._ws:
                await asyncio.sleep(1)
                continue
            try:
                raw_msg = await self._ws.recv()
            except websockets.ConnectionClosed as exc:
                logger.warning("WebSocket closed: %s", exc)
                self._connected_event.clear()
                break
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("WebSocket receive error: %s", exc)
                await asyncio.sleep(0.5)
                continue

            msg = self._ensure_dict(raw_msg)
            if msg is None:
                continue

            if msg.get("channel") == "error" or msg.get("type") == "error":
                logger.error("[WS_FEED][ERROR] subscribe_error msg=%s", msg)
                continue

            if not self._first_data_logged:
                self._first_data_logged = True
                channel = msg.get("channel") or msg.get("type") or "unknown"
                logger.info("[WS_FEED][INFO] first_data_received channel=%s", channel)
                self._first_data_event.set()

            if msg.get("channel") == "subscriptionResponse" or msg.get("type") == "subscriptionResponse":
                logger.info("[WS_FEED][INFO] subscriptionResponse msg=%s", msg)
                continue

            if self._raw_sample_logged < sample_limit:
                self._raw_sample_logged += 1
                try:
                    snippet = json.dumps(msg)
                except Exception:
                    snippet = str(msg)
                logger.info(
                    "[WS_FEED][SAMPLE] keys=%s msg=%s",
                    list(msg.keys()),
                    snippet[:500],
                )

            handled = False
            if self._is_l2book(msg):
                handled = True
                self._handle_l2book(msg)
            if self._is_mark_price(msg):
                handled = True
                self._handle_mark(msg)
            if self._is_all_mids(msg):
                handled = True
                self._handle_all_mids(msg)

            if handled and not self._first_market_logged:
                self._first_market_logged = True
                channel = msg.get("channel") or msg.get("type") or "unknown"
                logger.info("[WS_FEED][INFO] first_market_msg channel=%s keys=%s", channel, list(msg.keys()))

            if not handled:
                logger.debug("[WS_FEED][DEBUG] Unrecognized message: %s", msg)

    # Parsing helpers -------------------------------------------------------

    def _ensure_dict(self, raw_msg: Any) -> Optional[Dict[str, Any]]:
        if isinstance(raw_msg, dict):
            return raw_msg
        if isinstance(raw_msg, (bytes, bytearray)):
            try:
                raw_msg = raw_msg.decode()
            except Exception:
                logger.debug("[WS_FEED][DEBUG] Unable to decode bytes message: %s", raw_msg)
                return None
        if isinstance(raw_msg, str):
            try:
                return json.loads(raw_msg)
            except Exception:
                logger.debug("[WS_FEED][DEBUG] Failed to parse JSON: %s", raw_msg)
                return None
        logger.debug("[WS_FEED][DEBUG] Received non-JSON message: %s", raw_msg)
        return None

    def _is_l2book(self, msg: Dict[str, Any]) -> bool:
        if msg.get("channel") in {"l2Book", "l2book"}:
            return True
        if msg.get("type") in {"l2Book", "l2book"}:
            return True
        subscription = msg.get("subscription") or {}
        if isinstance(subscription, dict) and subscription.get("type") == "l2Book":
            return True
        data = msg.get("data") or msg.get("result")
        if isinstance(data, dict) and data.get("type") in {"l2Book", "l2book"}:
            return True
        return False

    def _is_mark_price(self, msg: Dict[str, Any]) -> bool:
        if msg.get("channel") in {"markPrice", "mark"}:
            return True
        if msg.get("type") == "markPrice":
            return True
        data = msg.get("data") or msg.get("result")
        if isinstance(data, dict) and data.get("type") == "markPrice":
            return True
        return False

    def _is_all_mids(self, msg: Dict[str, Any]) -> bool:
        if msg.get("channel") == "allMids":
            return True
        if msg.get("type") == "allMids":
            return True
        data = msg.get("data") or msg.get("result")
        if isinstance(data, dict) and data.get("type") == "allMids":
            return True
        return False

    async def _send_subscribe(self, sub: Dict[str, Any]) -> None:
        await self._connected_event.wait()
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        payload = {"method": "subscribe", "subscription": sub}
        logger.info("[WS_FEED][INFO] sending_subscribe payload=%s", json.dumps(payload))
        await self._ws.send(json.dumps(payload))

    def _handle_l2book(self, msg: Dict[str, Any]) -> None:
        payload = self._extract_payload(msg)
        coin = payload.get("coin") or payload.get("asset") or msg.get("coin") or msg.get("asset")
        if not coin:
            logger.debug("[WS_FEED][DEBUG] l2Book without coin: %s", msg)
            return

        levels = payload.get("levels") or payload
        bids = levels.get("bids") if isinstance(levels, dict) else None
        asks = levels.get("asks") if isinstance(levels, dict) else None
        bids = bids if isinstance(bids, list) else payload.get("bids") if isinstance(payload.get("bids"), list) else []
        asks = asks if isinstance(asks, list) else payload.get("asks") if isinstance(payload.get("asks"), list) else []

        best_bid = self._best_price(bids, reverse=True)
        best_ask = self._best_price(asks, reverse=False)
        best_bid = float(best_bid) if best_bid is not None else 0.0
        best_ask = float(best_ask) if best_ask is not None else 0.0
        ts = (
            payload.get("time")
            or payload.get("ts")
            or payload.get("timestamp")
            or msg.get("time")
            or msg.get("ts")
            or time.time()
        )

        norm = {"bid": best_bid, "ask": best_ask, "bids": bids, "asks": asks, "ts": ts}

        if not self._first_l2book_logged:
            self._first_l2book_logged = True
            logger.info(
                "[WS_FEED][INFO] first_l2book_received coin=%s bid=%s ask=%s", coin, best_bid, best_ask
            )

        kind, asset = self._detect_kind(payload, msg, coin)

        if kind == "perp":
            self._orderbooks_perp[asset] = norm
        else:
            self._orderbooks_spot[asset] = norm

        for cb in self._orderbook_listeners:
            try:
                cb(kind, asset, norm)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Orderbook listener error: %s", exc)

    def _handle_mark(self, msg: Dict[str, Any]) -> None:
        payload = self._extract_payload(msg)
        coin = payload.get("coin") or msg.get("coin")
        if not coin:
            logger.debug("[WS_FEED][DEBUG] markPrice without coin: %s", msg)
            return

        raw_mark = payload.get("markPx") or payload.get("mark") or payload.get("price") or msg.get("mark")
        try:
            mark = float(raw_mark)
        except Exception:
            mark = None
        ts = payload.get("time") or payload.get("ts") or payload.get("timestamp") or msg.get("time") or msg.get("ts")
        ts = ts or time.time()

        if mark is None:
            logger.debug("[WS_FEED][DEBUG] markPrice missing/invalid price: %s", msg)
            return

        base = self._mark_symbol_to_base.get(coin)
        if base is None:
            base = coin.split("/")[0] if isinstance(coin, str) and "/" in coin else coin
        self._marks[base] = mark

        for cb in self._mark_listeners:
            try:
                cb(base, mark, payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Mark listener error: %s", exc)

    def _handle_all_mids(self, msg: Dict[str, Any]) -> None:
        payload = msg.get("data") or msg.get("result") or {}
        if not isinstance(payload, dict):
            logger.debug("[WS_FEED][DEBUG] allMids unexpected payload: %s", msg)
            return
        mids = payload.get("mids") if isinstance(payload.get("mids"), dict) else None
        if mids is None:
            mids = payload.get("allMids") if isinstance(payload.get("allMids"), dict) else None
        if mids is None and all(isinstance(v, (int, float, str)) for v in payload.values()):
            mids = payload  # Already the mids map
        if not isinstance(mids, dict):
            logger.debug("[WS_FEED][DEBUG] allMids missing mids map: %s", msg)
            return

        if not self._first_allmids_logged:
            self._first_allmids_logged = True
            logger.info("[WS_FEED][INFO] first_allmids_received")

        self._mids_map = {}
        for coin, mid_val in mids.items():
            try:
                mid = float(mid_val)
            except Exception:
                logger.debug("[WS_FEED][DEBUG] invalid mid price coin=%s val=%s", coin, mid_val)
                continue
            self._mids_map[coin] = mid

        now = time.time()
        targets = self._tracked_bases or self._mark_subscriptions
        for base in targets:
            mid = None
            source_symbol = None
            for symbol in (base, f"{base}/USDC"):
                if symbol in self._mids_map:
                    mid = self._mids_map[symbol]
                    source_symbol = symbol
                    break
            if mid is None:
                continue
            self._marks[base] = mid
            payload_out = {"mid": mid, "time": now, "symbol": source_symbol or base}
            for cb in self._mark_listeners:
                try:
                    cb(base, mid, payload_out)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Mark listener error: %s", exc)

    def _extract_payload(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("data", "result", "payload"):
            val = msg.get(key)
            if isinstance(val, dict):
                return val
        return msg

    def _detect_kind(self, payload: Dict[str, Any], msg: Dict[str, Any], coin: str) -> tuple[str, str]:
        if coin in self._perp_symbol_to_base:
            return "perp", self._perp_symbol_to_base[coin]
        if coin in self._spot_symbol_to_base:
            return "spot", self._spot_symbol_to_base[coin]
        if payload.get("perp") or payload.get("isPerp") or payload.get("contractType") == "perp" or msg.get("isPerp"):
            return "perp", coin
        if isinstance(coin, str) and coin.endswith("/USDC"):
            return "spot", coin.split("/")[0]
        return "spot", coin

    def _best_price(self, levels: List[Any], reverse: bool) -> Optional[float]:
        best: Optional[float] = None
        for level in levels or []:
            price = None
            if isinstance(level, (list, tuple)) and level:
                try:
                    price = float(level[0])
                except Exception:
                    price = None
            elif isinstance(level, dict):
                candidate = level.get("px") or level.get("price") or level.get("p")
                try:
                    price = float(candidate)
                except Exception:
                    price = None
            if price is None:
                continue
            if best is None:
                best = price
            else:
                if reverse:
                    best = max(best, price)
                else:
                    best = min(best, price)
        return best

    async def close(self) -> None:
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
        if self._ws and not self._ws.closed:
            await self._ws.close()
        await self._session.aclose()

    def _normalize_spot_symbol(self, base: str) -> str:
        # Hyperliquid spot l2Book expects the base coin, not a "BASE/USDC" pair string.
        return base.split("/")[0]

    def _normalize_perp_symbol(self, base: str) -> str:
        return base.split("/")[0]


async def stream_orderbooks(client: HyperliquidClient, coins: Iterable[str]):
    await client.connect_ws()
    spot_map = {client._normalize_spot_symbol(coin): coin for coin in coins}
    await client.subscribe_orderbooks(spot_map, kind="spot")
    await client._ws_recv_loop()
