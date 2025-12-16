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

        # Subscriptions/bookkeeping
        self._orderbook_listeners: List[Callable[[str, str, Dict[str, Any]], None]] = []
        self._mark_listeners: List[Callable[[str, float, Dict[str, Any]], None]] = []
        self._recv_task: Optional[asyncio.Task] = None
        self._spot_subscriptions: set[str] = set()
        self._perp_subscriptions: set[str] = set()
        self._mark_subscriptions: set[str] = set()
        self._all_mids_subscribed = False
        self._l2book_subscribed = False
        self._raw_sample_logged = 0
        self._first_market_logged = False
        self._first_data_logged = False
        self._first_l2book_logged = False
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

    async def subscribe_orderbooks(self, coins: Iterable[str], kind: str = "spot") -> None:
        await self._connected_event.wait()
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        coins_list = list(coins)
        if kind == "perp":
            self._perp_subscriptions.update(coins_list)
        else:
            self._spot_subscriptions.update(coins_list)
        if self._l2book_subscribed:
            return
        for coin in coins_list:
            sub = {"method": "subscribe", "subscription": {"type": "l2Book", "coin": coin}}
            logger.info("[WS_FEED][INFO] sending_subscribe payload=%s", json.dumps(sub))
            await self._ws.send(json.dumps(sub))
            self._l2book_subscribed = True

    async def subscribe_mark_prices(self, coins: Iterable[str]) -> None:
        await self._connected_event.wait()
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        coins_list = list(coins)
        self._mark_subscriptions.update(coins_list)
        if self._all_mids_subscribed:
            return
        sub = {"method": "subscribe", "subscription": {"type": "allMids"}}
        logger.info("[WS_FEED][INFO] sending_subscribe payload=%s", json.dumps(sub))
        await self._ws.send(json.dumps(sub))
        self._all_mids_subscribed = True

    async def start_market_data(
        self,
        coins_spot: Iterable[str],
        coins_perp: Iterable[str],
        coins_mark: Iterable[str],
    ) -> None:
        coins_spot = ["BTC"]
        coins_perp = ["BTC"]
        coins_mark = ["BTC"]
        await self.connect_ws()
        if not self._recv_task or self._recv_task.done():
            self._recv_task = asyncio.create_task(self._ws_recv_loop())
        await self.subscribe_mark_prices(coins_mark)

        async def _delayed_l2book_subscribe() -> None:
            try:
                await asyncio.wait_for(self._first_data_event.wait(), timeout=3)
            except asyncio.TimeoutError:
                logger.info("[WS_FEED][INFO] first_data_wait_timeout sending l2Book subscribe")
            await self.subscribe_orderbooks(coins_spot, kind="spot")
            await self.subscribe_orderbooks(coins_perp, kind="perp")

        asyncio.create_task(_delayed_l2book_subscribe())

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

    def _handle_l2book(self, msg: Dict[str, Any]) -> None:
        payload = self._extract_payload(msg)
        coin = payload.get("coin") or payload.get("asset") or msg.get("coin") or msg.get("asset")
        if not coin:
            logger.debug("[WS_FEED][DEBUG] l2Book without coin: %s", msg)
            return

        if not self._first_l2book_logged:
            self._first_l2book_logged = True
            logger.info("[WS_FEED][INFO] first_l2book_received coin=%s", coin)

        levels = payload.get("levels") or payload
        bids = levels.get("bids") if isinstance(levels, dict) else None
        asks = levels.get("asks") if isinstance(levels, dict) else None
        bids = bids if isinstance(bids, list) else payload.get("bids") if isinstance(payload.get("bids"), list) else []
        asks = asks if isinstance(asks, list) else payload.get("asks") if isinstance(payload.get("asks"), list) else []

        best_bid = self._best_price(bids, reverse=True)
        best_ask = self._best_price(asks, reverse=False)
        ts = (
            payload.get("time")
            or payload.get("ts")
            or payload.get("timestamp")
            or msg.get("time")
            or msg.get("ts")
            or time.time()
        )

        norm = {"bid": best_bid, "ask": best_ask, "bids": bids, "asks": asks, "ts": ts}

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

        self._marks[coin] = mark

        for cb in self._mark_listeners:
            try:
                cb(coin, mark, payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Mark listener error: %s", exc)

    def _handle_all_mids(self, msg: Dict[str, Any]) -> None:
        payload = msg.get("data") or msg.get("result") or {}
        if not isinstance(payload, dict):
            logger.debug("[WS_FEED][DEBUG] allMids unexpected payload: %s", msg)
            return
        mids = payload.get("allMids") if isinstance(payload.get("allMids"), dict) else payload
        if not isinstance(mids, dict):
            logger.debug("[WS_FEED][DEBUG] allMids missing mids map: %s", msg)
            return
        for coin, mid_val in mids.items():
            if self._mark_subscriptions and coin not in self._mark_subscriptions:
                continue
            try:
                mid = float(mid_val)
            except Exception:
                logger.debug("[WS_FEED][DEBUG] invalid mid price coin=%s val=%s", coin, mid_val)
                continue
            self._marks[coin] = mid
            for cb in self._mark_listeners:
                try:
                    cb(coin, mid, {"mid": mid, "time": time.time()})
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Mark listener error: %s", exc)

    def _extract_payload(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("data", "result", "payload"):
            val = msg.get(key)
            if isinstance(val, dict):
                return val
        return msg

    def _detect_kind(self, payload: Dict[str, Any], msg: Dict[str, Any], coin: str) -> tuple[str, str]:
        if payload.get("perp") or payload.get("isPerp") or payload.get("contractType") == "perp":
            return "perp", coin
        if msg.get("perp") or msg.get("isPerp"):
            return "perp", coin

        if isinstance(coin, str) and coin.endswith("/USDC"):
            return "spot", coin.split("/")[0]

        in_spot = coin in self._spot_subscriptions
        in_perp = coin in self._perp_subscriptions
        if in_spot and not in_perp:
            return "spot", coin
        if in_perp and not in_spot:
            return "perp", coin
        if in_spot and in_perp:
            logger.warning("[WS_FEED][WARN] Ambiguous coin subscribed for spot and perp: %s", coin)
            return "spot", coin
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


async def stream_orderbooks(client: HyperliquidClient, coins: Iterable[str]):
    await client.connect_ws()
    await client.subscribe_orderbooks(coins)
    await client._ws_recv_loop()
