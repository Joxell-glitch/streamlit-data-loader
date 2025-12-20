from __future__ import annotations

import asyncio
import contextlib
import os
import json
import random
import time
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

import httpx
import websockets
from websockets.exceptions import WebSocketException

# websockets moved WebSocketClientProtocol from websockets.legacy.client to
# websockets.client in newer releases; try the modern path first and fall back
# for older versions to avoid runtime import errors across versions.
try:  # websockets >= 10
    from websockets.client import WebSocketClientProtocol
except ImportError:  # websockets < 10 compatibility
    from websockets.legacy.client import WebSocketClientProtocol  # type: ignore[attr-defined]

from src.config.models import APISettings
from src.core.logging import get_logger
from src.observability.feed_health import FeedHealthTracker

logger = get_logger(__name__)

BOOKS_IDLE_TIMEOUT = int(os.getenv("HL_BOOKS_IDLE_TIMEOUT", "20"))
BOOKS_SOCKET_CAP = int(os.getenv("HL_BOOKS_SOCKET_CAP", "3"))
SPOT_L2BOOK_WAIT_SECONDS = float(os.getenv("HL_SPOT_L2BOOK_WAIT_SECONDS", "3"))


class HyperliquidClient:
    """Thin wrapper around Hyperliquid REST and WebSocket APIs."""

    def __init__(
        self,
        api_settings: APISettings,
        network: str = "mainnet",
        feed_health_tracker: Optional[FeedHealthTracker] = None,
    ) -> None:
        self.api_settings = api_settings
        self.network = network
        self.feed_health_tracker = feed_health_tracker
        self._ws_market: Optional[WebSocketClientProtocol] = None
        self._ws_books: Dict[str, WebSocketClientProtocol] = {}
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
        self._recv_task_market: Optional[asyncio.Task] = None
        self._recv_tasks_books: Dict[str, asyncio.Task] = {}
        self._ws_runner_task_market: Optional[asyncio.Task] = None
        self._ws_runner_tasks_books: Dict[str, asyncio.Task] = {}
        self._spot_subscriptions: set[str] = set()
        self._perp_subscriptions: set[str] = set()
        self._mark_subscriptions: set[str] = set()
        self._sent_subscriptions_market: set[str] = set()
        self._sent_subscriptions_books: Dict[str, Dict[str, set[str]]] = {}
        self._all_mids_subscribed = False
        self._raw_sample_logged = 0
        self._first_market_logged = False
        self._first_data_logged = False
        self._first_l2book_logged = False
        self._first_allmids_logged = False
        self._mark_first_logged: set[str] = set()
        self._mark_ok: Dict[str, bool] = {}
        self._spot_first_valid_book_logged: set[str] = set()
        self._l2book_level_format_warned: set[str] = set()
        self._l2book_kind_logged: set[str] = set()
        self._first_data_event = asyncio.Event()
        self._payload_shape_logged = False
        self._payload_type_warned = False
        self._connected_event_market = asyncio.Event()
        self._connected_event_books = asyncio.Event()
        self._connected_event_books.set()
        self._books_connected_events: Dict[str, asyncio.Event] = {}
        self._logger = logger
        self._subscribe_delay_ms = self._get_subscribe_delay_ms()
        self._stopped = False
        self._reconnect_delay = 2
        self._books_last_l2book: Dict[str, Optional[float]] = {}
        self._books_watchdog_tasks: Dict[str, asyncio.Task] = {}
        self._books_idle_timeout = BOOKS_IDLE_TIMEOUT
        self._books_cap_warned = False
        self._spot_pair_map: Dict[str, str] = {}
        self._spot_ws_coin_choice: Dict[str, str] = {}
        self._spot_l2book_events: Dict[str, asyncio.Event] = {}
        self._reconnect_counters: Dict[str, Any] = {
            "market": 0,
            "books": {},
            "books_total": 0,
        }

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

    async def fetch_perp_meta(self) -> Dict[str, Any]:
        """
        Fetch perp market metadata (universe) from Hyperliquid.

        Hyperliquid exposes perp meta via the same /info endpoint using
        a \"meta\" request type. The returned payload contains a \"universe\"
        array with the available perp contracts.
        """
        url = f"{self.rest_base}{self.api_settings.info_path}"
        resp = await self._session.post(url, json={"type": "meta"})
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

    def set_feed_health_tracker(self, tracker: FeedHealthTracker) -> None:
        self.feed_health_tracker = tracker

    # WebSocket lifecycle ---------------------------------------------------

    async def connect_ws(self) -> None:
        async with self._ws_lock:
            if self._ws_runner_task_market and not self._ws_runner_task_market.done():
                await self._connected_event.wait()
                return
            self._stopped = False
            if not self._ws_runner_task_market or self._ws_runner_task_market.done():
                self._ws_runner_task_market = asyncio.create_task(
                    self._run_ws_loop(
                        name="WS_MARKET",
                        subscribe_fn=self._resubscribe_market,
                        set_ws_attr="_ws_market",
                        recv_task_attr="_recv_task_market",
                        sent_set=self._sent_subscriptions_market,
                        connected_event=self._connected_event_market,
                    )
                )
        await self._connected_event.wait()

    async def subscribe_orderbooks(self, symbol_map: Dict[str, str], kind: str = "spot") -> None:
        if os.getenv("HL_DISABLE_L2BOOK", "0") == "1":
            logger.info("[WS_FEED] HL_DISABLE_L2BOOK=1 -> skipping l2Book subscriptions")
            return
        if kind == "spot" and os.getenv("HL_DISABLE_SPOT_L2BOOK", "0") == "1":
            logger.info("[WS_FEED] HL_DISABLE_SPOT_L2BOOK=1 -> skipping spot l2Book")
            return
        if kind == "perp" and os.getenv("HL_DISABLE_PERP_L2BOOK", "0") == "1":
            logger.info("[WS_FEED] HL_DISABLE_PERP_L2BOOK=1 -> skipping perp l2Book")
            return

        items = list(symbol_map.items())
        if len(items) > BOOKS_SOCKET_CAP and not self._books_cap_warned:
            self._logger.warning(
                "[WS_BOOKS][WS_FEED] requested %s assets but cap=%s; only first %s will start",
                len(items),
                BOOKS_SOCKET_CAP,
                BOOKS_SOCKET_CAP,
            )
            self._books_cap_warned = True
        items = items[:BOOKS_SOCKET_CAP]

        for coin, base in items:
            if kind == "perp":
                perp_key = f"perp:{coin}"
                self._perp_subscriptions.add(perp_key)
                self._perp_symbol_to_base[coin] = base
            else:
                spot_key = f"spot:{coin}"
                self._spot_subscriptions.add(spot_key)
                self._spot_symbol_to_base[coin] = base
                self._spot_pair_map[coin] = base

            await self._ensure_books_runner(coin)
            await self._books_connected_events[coin].wait()
            if coin not in self._sent_subscriptions_books:
                self._sent_subscriptions_books[coin] = {"spot": set(), "perp": set()}
            if kind == "perp" and self._sent_subscriptions_books.get(coin, {}).get("spot"):
                logger.info(
                    "[WS_BOOKS_%s][WS_FEED] dual_subscribe spot+perp for same coin", coin
                )
            if kind == "spot" and self._sent_subscriptions_books.get(coin, {}).get("perp"):
                logger.info(
                    "[WS_BOOKS_%s][WS_FEED] dual_subscribe spot+perp for same coin", coin
                )
            logger.info("[WS_BOOKS_%s] subscribing single l2Book: %s (%s)", coin, coin, kind)

            try:
                snapshot = await self.fetch_orderbook_snapshot(coin)
                payload = self._extract_payload(snapshot)
                levels = payload.get("levels") or payload

                bids_source: Any = None
                asks_source: Any = None

                if isinstance(levels, dict):
                    bids_source = levels.get("bids")
                    asks_source = levels.get("asks")
                elif isinstance(levels, (list, tuple)) and len(levels) >= 2:
                    bids_source, asks_source = levels[0], levels[1]

                bids = (
                    bids_source
                    if isinstance(bids_source, list)
                    else payload.get("bids")
                    if isinstance(payload.get("bids"), list)
                    else []
                )
                asks = (
                    asks_source
                    if isinstance(asks_source, list)
                    else payload.get("asks")
                    if isinstance(payload.get("asks"), list)
                    else []
                )

                best_bid = self._best_price(bids, reverse=True)
                best_ask = self._best_price(asks, reverse=False)
                best_bid = float(best_bid) if best_bid is not None else 0.0
                best_ask = float(best_ask) if best_ask is not None else 0.0
                ts = (
                    payload.get("time")
                    or payload.get("ts")
                    or payload.get("timestamp")
                    or time.time()
                )

                norm = {"bid": best_bid, "ask": best_ask, "bids": bids, "asks": asks, "ts": ts}
                target_cache = self._orderbooks_perp if kind == "perp" else self._orderbooks_spot
                target_cache[base] = norm

                logger.info(
                    "[WS_BOOKS_%s][BOOTSTRAP] applied snapshot kind=%s bid=%s ask=%s",
                    coin,
                    kind,
                    best_bid,
                    best_ask,
                )
            except Exception as exc:
                logger.warning("[WS_BOOKS_%s][BOOTSTRAP] snapshot failed: %s", coin, exc)

            if kind == "spot":
                spot_pair = self._spot_pair_map.get(coin) or base
                await self._subscribe_spot_books(coin, spot_pair)
            else:
                await self._subscribe_books(coin, kind, coin)

    async def _ensure_books_runner(self, asset: str) -> None:
        if asset not in self._books_connected_events:
            self._books_connected_events[asset] = asyncio.Event()
        if asset not in self._sent_subscriptions_books:
            self._sent_subscriptions_books[asset] = {"spot": set(), "perp": set()}
        runner = self._ws_runner_tasks_books.get(asset)
        if runner and not runner.done():
            return
        self._stopped = False
        self._connected_event_books.clear()
        self._update_connected_event()
        self._ws_runner_tasks_books[asset] = asyncio.create_task(self._run_book_ws_loop(asset))

    async def subscribe_mark_prices(self, symbol_map: Dict[str, str]) -> None:
        await self._connected_event_market.wait()
        if not self._ws_market:
            raise RuntimeError("WebSocket not connected")
        for coin, base in symbol_map.items():
            sub_key = json.dumps({"type": "activeAssetCtx", "coin": coin}, sort_keys=True)
            self._mark_subscriptions.add(sub_key)
            self._mark_symbol_to_base[coin] = base
            await self._subscribe_market(coin)

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
        await self.connect_ws()
        if coins_mark_list:
            mark_symbols = {self._normalize_perp_symbol(base): base for base in coins_mark_list}
            await self.subscribe_mark_prices(mark_symbols)
        await self.subscribe_orderbooks(spot_symbols, kind="spot")
        await self.subscribe_orderbooks(perp_symbols, kind="perp")

    def _handle_ws_message(self, msg: Dict[str, Any]) -> None:
        if msg.get("channel") == "error" or msg.get("type") == "error":
            logger.error("[WS_FEED][ERROR] subscribe_error msg=%s", msg)
            return

        if not self._first_data_logged:
            self._first_data_logged = True
            channel = msg.get("channel") or msg.get("type") or "unknown"
            logger.info("[WS_FEED][INFO] first_data_received channel=%s", channel)
            self._first_data_event.set()

        if msg.get("channel") == "subscriptionResponse" or msg.get("type") == "subscriptionResponse":
            logger.info("[WS_FEED][INFO] subscriptionResponse msg=%s", msg)
            return

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
            tracker = getattr(self, "feed_health_tracker", None)
            if tracker:
                tracker.register_heartbeat(msg)
            logger.debug("[WS_FEED][DEBUG] Unrecognized message: %s", msg)

    async def _ws_recv_loop(
        self,
        ws: WebSocketClientProtocol,
        name: str,
        on_first_message: Optional[Callable[[], None]] = None,
        asset: Optional[str] = None,
    ) -> None:
        sample_limit = 5
        try:
            while True:
                try:
                    raw_msg = await ws.recv()
                except websockets.ConnectionClosed:
                    raise
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("WebSocket receive error (%s): %s", name, exc)
                    await asyncio.sleep(0.5)
                    continue

                if on_first_message:
                    on_first_message()
                    on_first_message = None

                parsed_msg = self._ensure_dict(raw_msg)
                if parsed_msg is None:
                    continue

                if isinstance(parsed_msg, list):
                    self._log_payload_shape(parsed_msg)
                    for item in parsed_msg:
                        if isinstance(item, dict):
                            self._handle_ws_message(item)
                    continue

                for msg in self._iterate_payload(parsed_msg):
                    tracker = getattr(self, "feed_health_tracker", None)
                    if tracker:
                        try:
                            dedup_input = msg if isinstance(msg, dict) else {"raw": raw_msg}
                            duplicate = tracker.register_message(dedup_input)
                        except Exception:
                            duplicate = False
                        if duplicate:
                            logger.debug("[%s][WS_FEED] duplicate message dropped", name)
                            continue
                    if isinstance(msg, dict):
                        ch = msg.get("channel")
                        keys = list(msg.keys())
                        dkeys = list(msg.get("data", {}).keys()) if isinstance(msg.get("data"), dict) else None
                        self._logger.info(
                            "[%s][RAW_RECV] channel=%s keys=%s data_keys=%s", name, ch, keys, dkeys
                        )
                    else:
                        self._logger.info("[%s][RAW_RECV] non-dict msg=%r", name, raw_msg)
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
                    if name.startswith("WS_BOOKS") and self._is_l2book(msg):
                        payload = self._extract_payload(msg)
                        coin = payload.get("coin") or payload.get("asset") or msg.get("coin") or msg.get("asset")
                        target_asset = coin if isinstance(coin, str) else asset
                        if target_asset:
                            self._books_last_l2book[target_asset] = time.monotonic()
                    self._handle_ws_message(msg)
        except websockets.ConnectionClosed as e:
            self._logger.warning(
                "[%s] recv loop ConnectionClosed code=%s reason=%s",
                name,
                getattr(e, "code", None),
                getattr(e, "reason", None),
            )
            if name.startswith("WS_BOOKS"):
                self._register_reconnect("books", asset, getattr(e, "code", None))
            else:
                self._register_reconnect("market", None, getattr(e, "code", None))
            raise
        except Exception:
            self._logger.exception("[%s] recv loop crashed", name)
            raise

    async def _run_book_ws_loop(self, asset: str) -> None:
        name = f"WS_BOOKS_{asset}"
        reconnect_attempt = 0
        books_failure_streak = 0
        while not self._stopped:
            await self._reset_book_connection(asset)
            if reconnect_attempt:
                self._logger.info("[%s] reconnect attempt %s", name, reconnect_attempt)
            sleep_delay = self._reconnect_delay
            try:
                self._logger.info("Connecting to Hyperliquid WebSocket (%s): %s", name, self.websocket_url)
                ws = await websockets.connect(
                    self.websocket_url,
                    ping_interval=5,
                    ping_timeout=5,
                    close_timeout=5,
                )
                self._ws_books[asset] = ws
                self._books_connected_events[asset].set()
                self._update_books_connected_event()
                self._logger.info("[%s] WebSocket connected", name)

                def _reset_backoff() -> None:
                    nonlocal books_failure_streak
                    books_failure_streak = 0

                recv_task = asyncio.create_task(
                    self._ws_recv_loop(ws, name, _reset_backoff, asset)
                )
                self._recv_tasks_books[asset] = recv_task
                self._books_last_l2book[asset] = time.monotonic()
                await self._cancel_books_watchdog(asset)
                self._books_watchdog_tasks[asset] = asyncio.create_task(
                    self._books_idle_watchdog(ws, asset)
                )
                await self._resubscribe_books(asset, reconnect_attempt > 0)
                await recv_task
            except websockets.ConnectionClosed as e:
                self._books_connected_events[asset].clear()
                self._connected_event_books.clear()
                self._connected_event.clear()
                books_failure_streak += 1
                self._register_reconnect("books", asset, type(e).__name__)
                base_delay = min(self._reconnect_delay * (2 ** (books_failure_streak - 1)), 30)
                sleep_delay = min(base_delay * random.uniform(0.8, 1.2), 30)
                self._logger.warning(
                    "[%s] reconnect after %s, sleeping %.1fs (attempt %s)",
                    name,
                    type(e).__name__,
                    sleep_delay,
                    books_failure_streak,
                )
                self._update_books_connected_event()
            except Exception as e:  # pragma: no cover - defensive
                self._books_connected_events[asset].clear()
                self._connected_event_books.clear()
                self._connected_event.clear()
                books_failure_streak += 1
                self._register_reconnect("books", asset, type(e).__name__)
                base_delay = min(self._reconnect_delay * (2 ** (books_failure_streak - 1)), 30)
                sleep_delay = min(base_delay * random.uniform(0.8, 1.2), 30)
                self._logger.warning(
                    "[%s] reconnect after %s, sleeping %.1fs (attempt %s)",
                    name,
                    type(e).__name__,
                    sleep_delay,
                    books_failure_streak,
                )
                self._logger.debug("[%s] error detail: %s", name, e)
                self._update_books_connected_event()
            reconnect_attempt += 1
            if self._stopped:
                break
            await asyncio.sleep(sleep_delay)

    async def _run_ws_loop(
        self,
        name: str,
        subscribe_fn: Callable[[bool], Awaitable[None]],
        set_ws_attr: str,
        recv_task_attr: str,
        sent_set: set[str],
        connected_event: asyncio.Event,
    ) -> None:
        reconnect_attempt = 0
        books_failure_streak = 0
        while not self._stopped:
            await self._reset_connection(set_ws_attr, recv_task_attr, sent_set, connected_event)
            if reconnect_attempt:
                self._logger.info("[%s] reconnect attempt %s", name, reconnect_attempt)
            sleep_delay = self._reconnect_delay
            try:
                self._logger.info("Connecting to Hyperliquid WebSocket (%s): %s", name, self.websocket_url)
                ws = await websockets.connect(
                    self.websocket_url,
                    ping_interval=5,
                    ping_timeout=5,
                    close_timeout=5,
                )
                setattr(self, set_ws_attr, ws)
                connected_event.set()
                self._update_connected_event()
                self._logger.info("[%s] WebSocket connected", name)
                first_message_reset: Optional[Callable[[], None]] = None
                if name == "WS_BOOKS":

                    def _reset_backoff() -> None:
                        nonlocal books_failure_streak
                        books_failure_streak = 0

                    first_message_reset = _reset_backoff

                recv_task = asyncio.create_task(
                    self._ws_recv_loop(ws, name, first_message_reset)
                )
                setattr(self, recv_task_attr, recv_task)
                await subscribe_fn(reconnect_attempt > 0)
                await recv_task
            except websockets.ConnectionClosed as e:
                connected_event.clear()
                self._connected_event.clear()
                if name == "WS_BOOKS":
                    books_failure_streak += 1
                    self._register_reconnect("books", None, type(e).__name__)
                    base_delay = min(self._reconnect_delay * (2 ** (books_failure_streak - 1)), 30)
                    sleep_delay = min(base_delay * random.uniform(0.8, 1.2), 30)
                    self._logger.warning(
                        "[%s] reconnect after %s, sleeping %.1fs (attempt %s)",
                        name,
                        type(e).__name__,
                        sleep_delay,
                        books_failure_streak,
                    )
                else:
                    self._logger.warning(
                        "[%s] WS closed (%s). Reconnecting in %ss...",
                        name,
                        e,
                        self._reconnect_delay,
                    )
            except Exception as e:  # pragma: no cover - defensive
                connected_event.clear()
                self._connected_event.clear()
                if name == "WS_BOOKS":
                    books_failure_streak += 1
                    self._register_reconnect("books", None, type(e).__name__)
                    base_delay = min(self._reconnect_delay * (2 ** (books_failure_streak - 1)), 30)
                    sleep_delay = min(base_delay * random.uniform(0.8, 1.2), 30)
                    self._logger.warning(
                        "[%s] reconnect after %s, sleeping %.1fs (attempt %s)",
                        name,
                        type(e).__name__,
                        sleep_delay,
                        books_failure_streak,
                    )
                else:
                    self._logger.error("[%s] WS crash: %s", name, e)
            reconnect_attempt += 1
            if self._stopped:
                break
            await asyncio.sleep(sleep_delay)

    async def _reset_connection(
        self,
        ws_attr: str,
        recv_task_attr: str,
        sent_set: set[str],
        connected_event: asyncio.Event,
    ) -> None:
        connected_event.clear()
        self._connected_event.clear()
        sent_set.clear()
        recv_task = getattr(self, recv_task_attr)
        if recv_task and not recv_task.done():
            recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await recv_task
        setattr(self, recv_task_attr, None)
        if ws_attr == "_ws_books":
            await self._cancel_books_watchdog()
        ws = getattr(self, ws_attr)
        if ws and not ws.closed:
            await ws.close()
        setattr(self, ws_attr, None)

    async def _reset_book_connection(self, asset: str) -> None:
        event = self._books_connected_events.setdefault(asset, asyncio.Event())
        event.clear()
        self._connected_event_books.clear()
        self._connected_event.clear()
        sent_set = self._sent_subscriptions_books.get(asset)
        if sent_set is not None:
            for kind_set in sent_set.values():
                kind_set.clear()
        recv_task = self._recv_tasks_books.get(asset)
        if recv_task and not recv_task.done():
            recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await recv_task
        self._recv_tasks_books.pop(asset, None)
        await self._cancel_books_watchdog(asset)
        ws = self._ws_books.get(asset)
        if ws and not ws.closed:
            await ws.close()
        self._ws_books.pop(asset, None)
        self._books_last_l2book.pop(asset, None)
        self._update_books_connected_event()

    def _update_connected_event(self) -> None:
        if self._connected_event_market.is_set() and self._connected_event_books.is_set():
            self._connected_event.set()
        else:
            self._connected_event.clear()

    def _update_books_connected_event(self) -> None:
        active_assets = [asset for asset, task in self._ws_runner_tasks_books.items() if task and not task.done()]
        if not active_assets:
            self._connected_event_books.set()
        else:
            ready = all(self._books_connected_events.get(asset) and self._books_connected_events[asset].is_set() for asset in active_assets)
            if ready:
                self._connected_event_books.set()
            else:
                self._connected_event_books.clear()
        self._update_connected_event()

    async def _resubscribe_market(self, is_reconnect: bool) -> None:
        if self._mark_symbol_to_base:
            await self.subscribe_mark_prices(self._mark_symbol_to_base)
        if is_reconnect and self._mark_symbol_to_base:
            self._logger.info("[WS_MARKET][WS_FEED] resubscribed after reconnect")

    async def _resubscribe_books(self, asset: str, is_reconnect: bool) -> None:
        symbol_entries: list[tuple[str, Dict[str, str]]] = []
        if asset in self._spot_symbol_to_base:
            symbol_entries.append(("spot", {asset: self._spot_symbol_to_base[asset]}))
        if asset in self._perp_symbol_to_base:
            symbol_entries.append(("perp", {asset: self._perp_symbol_to_base[asset]}))
        for kind, symbol_entry in symbol_entries:
            await self.subscribe_orderbooks(symbol_entry, kind=kind)
            if is_reconnect:
                self._logger.info(
                    "[WS_BOOKS_%s][WS_FEED] resubscribed after reconnect (%s)", asset, kind
                )

    # Parsing helpers -------------------------------------------------------

    def _ensure_dict(self, raw_msg: Any) -> Optional[Any]:
        if isinstance(raw_msg, (dict, list)):
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
        if msg.get("channel") in {"activeAssetCtx"}:
            return True
        if msg.get("type") in {"markPrice", "activeAssetCtx"}:
            return True
        subscription = msg.get("subscription") or {}
        if isinstance(subscription, dict) and subscription.get("type") == "activeAssetCtx":
            return True
        data = msg.get("data") or msg.get("result")
        if isinstance(data, dict) and data.get("type") in {"markPrice", "activeAssetCtx"}:
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

    async def _subscribe_market(self, coin: str) -> None:
        sub_payload = {"type": "activeAssetCtx", "coin": coin}
        await self._send_subscribe_ws(
            sub_payload,
            ws_attr="_ws_market",
            sent_set=self._sent_subscriptions_market,
            name="WS_MARKET",
        )

    async def _subscribe_books(self, payload_coin: str, kind: str, asset: str) -> None:
        if os.getenv("HL_DISABLE_L2BOOK", "0") == "1":
            logger.info("[WS_FEED] HL_DISABLE_L2BOOK=1 -> skipping l2Book subscriptions")
            return
        if kind == "spot" and os.getenv("HL_DISABLE_SPOT_L2BOOK", "0") == "1":
            logger.info("[WS_FEED] HL_DISABLE_SPOT_L2BOOK=1 -> skipping spot l2Book")
            return
        if kind == "perp" and os.getenv("HL_DISABLE_PERP_L2BOOK", "0") == "1":
            logger.info("[WS_FEED] HL_DISABLE_PERP_L2BOOK=1 -> skipping perp l2Book")
            return
        sub_payload: Dict[str, Any] = {"type": "l2Book", "coin": payload_coin}
        if kind == "perp":
            sub_payload["isPerp"] = True
        await self._send_subscribe_ws(
            sub_payload,
            ws_attr="_ws_books",
            sent_set=self._sent_subscriptions_books[asset][kind],
            name=f"WS_BOOKS_{asset}",
            asset=asset,
        )
        await asyncio.sleep(self._subscribe_delay_ms / 1000.0)

    async def _subscribe_spot_books(self, asset: str, spot_pair: str) -> None:
        if os.getenv("HL_DISABLE_L2BOOK", "0") == "1":
            logger.info("[WS_FEED] HL_DISABLE_L2BOOK=1 -> skipping l2Book subscriptions")
            return
        if os.getenv("HL_DISABLE_SPOT_L2BOOK", "0") == "1":
            logger.info("[WS_FEED] HL_DISABLE_SPOT_L2BOOK=1 -> skipping spot l2Book")
            return

        primary_coin, fallback_coin = self._resolve_spot_ws_coin(spot_pair)
        asset_key = self._spot_symbol_to_base.get(asset, spot_pair) or asset
        if fallback_coin:
            self._spot_symbol_to_base.setdefault(fallback_coin, asset_key)
        l2_event = self._spot_l2book_events.setdefault(asset_key, asyncio.Event())
        l2_event.clear()

        async def _do_subscribe(candidate: str) -> None:
            try:
                await self._send_subscribe_ws(
                    {"type": "l2Book", "coin": candidate},
                    ws_attr="_ws_books",
                    sent_set=self._sent_subscriptions_books[asset]["spot"],
                    name=f"WS_BOOKS_{asset}",
                    asset=asset,
                )
            except WebSocketException as exc:
                self._sent_subscriptions_books[asset]["spot"].discard(
                    json.dumps({"type": "l2Book", "coin": candidate}, sort_keys=True)
                )
                raise exc

        try:
            await _do_subscribe(primary_coin)
        except WebSocketException as exc:
            if fallback_coin != primary_coin:
                logger.info(
                    "[WS_BOOKS_%s] SPOT WS coin resolved: %s -> %s (fallback after send failure %s)",
                    asset_key,
                    primary_coin,
                    fallback_coin,
                    type(exc).__name__,
                )
                await _do_subscribe(fallback_coin)
                self._spot_ws_coin_choice[asset_key] = fallback_coin
                await asyncio.sleep(self._subscribe_delay_ms / 1000.0)
                return
            raise

        await asyncio.sleep(self._subscribe_delay_ms / 1000.0)
        try:
            await asyncio.wait_for(l2_event.wait(), timeout=SPOT_L2BOOK_WAIT_SECONDS)
            self._spot_ws_coin_choice.setdefault(asset_key, primary_coin)
            return
        except asyncio.TimeoutError:
            if fallback_coin == primary_coin:
                return
            logger.info(
                "[WS_BOOKS_%s] SPOT WS coin resolved: %s -> %s (fallback after no l2Book)",
                asset_key,
                primary_coin,
                fallback_coin,
            )
            self._sent_subscriptions_books[asset]["spot"].discard(
                json.dumps({"type": "l2Book", "coin": primary_coin}, sort_keys=True)
            )
            await _do_subscribe(fallback_coin)
            try:
                await asyncio.wait_for(l2_event.wait(), timeout=SPOT_L2BOOK_WAIT_SECONDS)
            except asyncio.TimeoutError:
                logger.warning(
                    "[WS_BOOKS_%s][WARN] fallback coin=%s still no l2Book after %.1fs",
                    asset_key,
                    fallback_coin,
                    SPOT_L2BOOK_WAIT_SECONDS,
                )
            self._spot_ws_coin_choice[asset_key] = fallback_coin
            await asyncio.sleep(self._subscribe_delay_ms / 1000.0)

    async def _send_subscribe_ws(
        self,
        sub: Dict[str, Any],
        ws_attr: str,
        sent_set: set[str],
        name: str,
        asset: Optional[str] = None,
    ) -> None:
        ws = None
        if ws_attr == "_ws_books" and asset:
            ws = self._ws_books.get(asset)
        else:
            ws = getattr(self, ws_attr)
        if not ws:
            raise RuntimeError(f"WebSocket not connected for {name}")
        key = json.dumps(sub, sort_keys=True)
        if key in sent_set:
            logger.info("[%s][WS_FEED] Already subscribed key=%s", name, key)
            return
        sent_set.add(key)
        payload = {"method": "subscribe", "subscription": sub}
        logger.info("[%s][WS_FEED] sent subscribe sub=%s", name, json.dumps(sub, sort_keys=True))
        logger.info("[%s][WS_FEED][INFO] sending_subscribe payload=%s", name, json.dumps(payload))
        await ws.send(json.dumps(payload))

    def _handle_l2book(self, msg: Dict[str, Any]) -> None:
        payload = self._extract_payload(msg)
        coin = payload.get("coin") or payload.get("asset") or msg.get("coin") or msg.get("asset")
        if not coin:
            logger.debug("[WS_FEED][DEBUG] l2Book without coin: %s", msg)
            return

        levels = payload.get("levels") or payload
        bids_source: Any = None
        asks_source: Any = None

        if isinstance(levels, dict):
            bids_source = levels.get("bids")
            asks_source = levels.get("asks")
        elif isinstance(levels, (list, tuple)) and len(levels) >= 2:
            bids_source, asks_source = levels[0], levels[1]
        else:
            if coin not in self._l2book_level_format_warned:
                self._l2book_level_format_warned.add(coin)
                logger.warning(
                    "[WS_FEED][WARN] l2Book unexpected levels format coin=%s type=%s", coin, type(levels).__name__
                )

        bids = bids_source if isinstance(bids_source, list) else payload.get("bids") if isinstance(payload.get("bids"), list) else []
        asks = asks_source if isinstance(asks_source, list) else payload.get("asks") if isinstance(payload.get("asks"), list) else []

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

        kind, asset, reason = self._detect_kind(payload, msg, coin)

        if asset not in self._l2book_kind_logged:
            self._l2book_kind_logged.add(asset)
            logger.info(
                "[WS_FEED][INFO] l2book_kind_resolved asset=%s kind=%s reason=%s", asset, kind, reason
            )

        if kind == "perp":
            self._orderbooks_perp[asset] = norm
        else:
            self._orderbooks_spot[asset] = norm
            event = self._spot_l2book_events.get(asset)
            if event and not event.is_set():
                event.set()
                resolved_coin = self._spot_ws_coin_choice.get(asset)
                if resolved_coin and resolved_coin != coin:
                    logger.info(
                        "[WS_BOOKS_%s] SPOT WS coin resolved: %s -> %s (from payload)",
                        asset,
                        resolved_coin,
                        coin,
                    )
                self._spot_ws_coin_choice[asset] = coin

            if (
                asset not in self._spot_first_valid_book_logged
                and len(bids) > 0
                and len(asks) > 0
                and best_bid > 0
                and best_ask > 0
            ):
                self._spot_first_valid_book_logged.add(asset)
                logger.info(
                    "[WS_FEED][INFO] first_valid_spot_book asset=%s best_bid=%s best_ask=%s",
                    asset,
                    best_bid,
                    best_ask,
                )

        tracker = getattr(self, "feed_health_tracker", None)
        if tracker:
            tracker.on_book_update(asset, kind, best_bid, best_ask, ts, bids, asks)

        for cb in self._orderbook_listeners:
            try:
                cb(kind, asset, norm)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Orderbook listener error: %s", exc)

    def _handle_mark(self, msg: Dict[str, Any]) -> None:
        payload = self._extract_payload(msg)
        ctx = payload.get("ctx") if isinstance(payload.get("ctx"), dict) else None

        is_active_ctx = False
        if msg.get("channel") == "activeAssetCtx" or msg.get("type") == "activeAssetCtx":
            is_active_ctx = True
        data_field = msg.get("data") or msg.get("result")
        if isinstance(data_field, dict) and data_field.get("type") == "activeAssetCtx":
            is_active_ctx = True
        if isinstance(payload, dict) and (payload.get("type") == "activeAssetCtx" or ctx is not None):
            is_active_ctx = True

        coin = payload.get("coin") or msg.get("coin")
        if not coin and ctx:
            coin = ctx.get("coin")
        if not coin:
            logger.debug("[WS_FEED][DEBUG] markPrice without coin: %s", msg)
            return

        raw_mark = None
        if is_active_ctx and ctx:
            for key in ("markPx", "mark", "price"):
                if key in ctx:
                    raw_mark = ctx.get(key)
                    break
        if raw_mark is None:
            raw_mark = (
                payload.get("markPx")
                or payload.get("mark")
                or payload.get("price")
                or msg.get("mark")
            )
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

        if base not in self._mark_first_logged:
            self._mark_first_logged.add(base)
            logger.info("[WS_FEED][INFO] first_mark_received asset=%s", base)
        self._mark_ok[base] = True

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
        targets = self._tracked_bases or set(self._mark_symbol_to_base.values())
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

    def _detect_kind(
        self, payload: Dict[str, Any], msg: Dict[str, Any], coin: str
    ) -> tuple[str, str, str]:
        subscription = msg.get("subscription") if isinstance(msg.get("subscription"), dict) else {}
        is_perp = payload.get("perp") or payload.get("isPerp") or payload.get("contractType") == "perp"
        is_perp = is_perp or msg.get("isPerp") or (isinstance(subscription, dict) and subscription.get("isPerp"))
        if is_perp:
            return "perp", self._perp_symbol_to_base.get(coin, coin), "payload_flag"
        if coin in self._perp_symbol_to_base:
            return "perp", self._perp_symbol_to_base[coin], "perp_map"
        if coin in self._spot_symbol_to_base:
            return "spot", self._spot_symbol_to_base[coin], "spot_map"
        if isinstance(coin, str) and coin.endswith("/USDC"):
            return "spot", coin.split("/")[0], "symbol_suffix"
        return "spot", coin, "default"

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

    def _iterate_payload(self, payload: Any) -> List[Dict[str, Any]]:
        self._log_payload_shape(payload)
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            msgs: List[Dict[str, Any]] = []
            for item in payload:
                if isinstance(item, dict):
                    msgs.append(item)
                else:
                    self._log_unhandled_payload(item)
            return msgs
        self._log_unhandled_payload(payload)
        return []

    def _log_payload_shape(self, payload: Any) -> None:
        if self._payload_shape_logged:
            return
        if isinstance(payload, list):
            first_item = payload[0] if payload else None
            first_type = type(first_item).__name__ if first_item is not None else None
            first_keys = list(first_item.keys()) if isinstance(first_item, dict) else None
            logger.info(
                "[WS_FEED][INFO] payload_shape type=%s len=%s first_type=%s first_keys=%s",
                type(payload).__name__,
                len(payload),
                first_type,
                first_keys,
            )
        elif isinstance(payload, dict):
            logger.info(
                "[WS_FEED][INFO] payload_shape type=%s keys=%s",
                type(payload).__name__,
                list(payload.keys()),
            )
        else:
            self._log_unhandled_payload(payload)
            return
        self._payload_shape_logged = True

    def _log_unhandled_payload(self, payload: Any) -> None:
        if self._payload_type_warned:
            return
        logger.warning(
            "[WS_FEED][WARN] unhandled WS payload type=%s sample=%r",
            type(payload).__name__,
            payload,
        )
        self._payload_type_warned = True

    async def close(self) -> None:
        self._stopped = True
        tasks_to_cancel = [self._ws_runner_task_market, *self._ws_runner_tasks_books.values()]
        for task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        recv_tasks = [self._recv_task_market, *self._recv_tasks_books.values()]
        for task in recv_tasks:
            if task and not getattr(task, "done", lambda: True)():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        for ws in [self._ws_market, *self._ws_books.values()]:
            if ws and not ws.closed:
                await ws.close()
        await self._cancel_books_watchdog()
        await self._session.aclose()

    # ------------------------------------------------------------------
    # Metrics / status helpers

    def _register_reconnect(self, kind: str, asset: Optional[str], reason: Any) -> None:
        if kind == "market":
            self._reconnect_counters["market"] += 1
            self._logger.info(
                "[WS_%s] disconnect detected (reason=%s) total_reconnects=%s",
                kind.upper(),
                reason,
                self._reconnect_counters["market"],
            )
            return

        if kind == "books":
            asset_key = asset or "_shared"
            self._reconnect_counters["books_total"] += 1
            books_map: Dict[str, int] = self._reconnect_counters.setdefault("books", {})
            books_map[asset_key] = books_map.get(asset_key, 0) + 1
            self._logger.info(
                "[WS_BOOKS_%s] disconnect detected (reason=%s) total_reconnects=%s",
                asset_key,
                reason,
                books_map[asset_key],
            )

    @property
    def reconnect_counts(self) -> Dict[str, Any]:
        """Return a snapshot of reconnect counters for monitoring/metrics."""

        return {
            "market": self._reconnect_counters.get("market", 0),
            "books_total": self._reconnect_counters.get("books_total", 0),
            "books": dict(self._reconnect_counters.get("books", {})),
        }

    async def _books_idle_watchdog(self, ws: WebSocketClientProtocol, asset: Optional[str] = None) -> None:
        try:
            while True:
                await asyncio.sleep(1)
                last_seen = self._books_last_l2book.get(asset) if asset else None
                if last_seen is None:
                    continue
                idle = time.monotonic() - last_seen
                if idle > self._books_idle_timeout:
                    name = f"WS_BOOKS_{asset}" if asset else "WS_BOOKS"
                    self._logger.warning(
                        "[%s] idle watchdog: no l2Book for %.1fs -> closing ws to reconnect",
                        name,
                        idle,
                    )
                    with contextlib.suppress(Exception):
                        if not ws.closed:
                            await ws.close()
                    break
        except asyncio.CancelledError:
            raise
        finally:
            if asset:
                task = self._books_watchdog_tasks.get(asset)
                if task is asyncio.current_task():
                    self._books_watchdog_tasks[asset] = None  # type: ignore[assignment]

    async def _cancel_books_watchdog(self, asset: Optional[str] = None) -> None:
        if asset:
            task = self._books_watchdog_tasks.get(asset)
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._books_watchdog_tasks[asset] = None  # type: ignore[assignment]
        else:
            for task_asset, task in list(self._books_watchdog_tasks.items()):
                if task and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                self._books_watchdog_tasks[task_asset] = None  # type: ignore[assignment]

    def _normalize_spot_symbol(self, base: str) -> str:
        # Hyperliquid spot l2Book expects the base coin, not a "BASE/USDC" pair string.
        return base.split("/")[0]

    def _normalize_perp_symbol(self, base: str) -> str:
        return base.split("/")[0]

    SPECIAL_SPOT_WS_CANONICAL = {"PURR/USDC"}

    def _resolve_spot_ws_coin(self, spot_pair: str) -> tuple[str, str]:
        """
        Resolve the coin string to use for spot l2Book subscriptions.

        Primary attempt: use the current behaviour (often \"@{index}\" from the pair string).
        Fallback: use the explicit \"BASE/QUOTE\" pair which is accepted by the WS for spots like PURR/USDC.
        """
        pair = (spot_pair or "").strip().upper()
        if pair in self.SPECIAL_SPOT_WS_CANONICAL:
            primary = pair
            fallback = pair.split("/", 1)[0]
            return primary, fallback

        if "/" in pair:
            base, quote = pair.split("/", 1)
        else:
            base, quote = pair, "USDC"

        primary = base
        if base.startswith("@"):
            primary = base

        fallback = f"{base}/{quote}"
        return primary, fallback

    def _get_subscribe_delay_ms(self) -> int:
        try:
            return int(os.getenv("HL_SUBSCRIBE_DELAY_MS", "200"))
        except ValueError:
            return 200

    def get_resolved_spot_coin(self, asset: str) -> Optional[str]:
        """
        Return the resolved spot WS coin string used for subscriptions for the given asset.
        """
        asset_key = self._spot_symbol_to_base.get(asset, asset)
        return self._spot_ws_coin_choice.get(asset_key)

    async def wait_for_spot_l2book(self, asset: str, timeout: float = SPOT_L2BOOK_WAIT_SECONDS) -> bool:
        """
        Wait for a spot l2Book message for the given asset (base or pair). Returns True if received.
        """
        asset_key = self._spot_symbol_to_base.get(asset, asset)
        event = self._spot_l2book_events.setdefault(asset_key, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


async def stream_orderbooks(client: HyperliquidClient, coins: Iterable[str]):
    await client.connect_ws()
    spot_map = {client._normalize_spot_symbol(coin): coin for coin in coins}
    await client.subscribe_orderbooks(spot_map, kind="spot")
    if client._ws_books:
        asset, ws = next(iter(client._ws_books.items()))
        await client._ws_recv_loop(ws, f"WS_BOOKS_{asset}", asset=asset)
