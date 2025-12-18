from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.config.loader import load_config
from src.config.models import FeedHealthSettings, Settings, TradingSettings
from src.core.logging import get_logger
from src.db.models import SpotPerpOpportunity
from src.db.session import get_session
from src.hyperliquid_client.client import HyperliquidClient
from src.observability.feed_health import FeedHealthTracker

logger = get_logger(__name__)


@dataclass
class BookSnapshot:
    best_bid: float = 0.0
    best_ask: float = 0.0
    ts: float = 0.0

    @classmethod
    def from_levels(cls, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]):
        bid_price = max(bids, key=lambda x: x[0])[0] if bids else 0.0
        ask_price = min(asks, key=lambda x: x[0])[0] if asks else 0.0
        return cls(best_bid=bid_price, best_ask=ask_price)

    def has_liquidity(self) -> bool:
        return self.best_bid > 0 and self.best_ask > 0


@dataclass
class AssetState:
    spot: BookSnapshot = field(default_factory=BookSnapshot)
    perp: BookSnapshot = field(default_factory=BookSnapshot)
    mark_price: float = 0.0
    funding_rate: float = 0.0
    mark_ts: float = 0.0

    def ready(self) -> bool:
        return self.spot.has_liquidity() and self.perp.has_liquidity() and self.mark_price > 0


class SpotPerpPaperEngine:
    """
    Paper engine that observes spot and perp books to estimate arbitrage edge.

    No real orders are sent. The engine only logs and persists opportunities
    when the estimated net PnL is positive.
    """

    def __init__(
        self,
        client: HyperliquidClient,
        assets: Iterable[str],
        trading: TradingSettings,
        db_session_factory=get_session,
        taker_fee_spot: float = 0.001,
        taker_fee_perp: float = 0.0005,
        feed_health_settings: Optional[FeedHealthSettings] = None,
        feed_health_tracker: Optional[FeedHealthTracker] = None,
    ) -> None:
        self.client = client
        self.assets = list(assets)
        self.trading = trading
        self.taker_fee_spot = taker_fee_spot
        self.taker_fee_perp = taker_fee_perp
        self.db_session_factory = db_session_factory
        self.feed_health = feed_health_tracker or FeedHealthTracker(feed_health_settings)
        self.client.set_feed_health_tracker(self.feed_health)
        self.asset_state: Dict[str, AssetState] = {asset: AssetState() for asset in self.assets}
        self._running = False
        self._heartbeat_interval = 10
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._feed_health_task: Optional[asyncio.Task] = None
        self._last_heartbeat = time.time()
        self._metrics_interval = float(os.getenv("SPOT_PERP_METRICS_INTERVAL", "30"))
        self._last_metrics_log = time.time()
        self.opportunities_seen = 0
        self.trades_executed = 0
        self.pnl_estimated = 0.0
        self._pnl_peak = 0.0
        self.max_drawdown = 0.0
        self.update_counts: Dict[str, Dict[str, int]] = {
            asset: {"spot": 0, "perp": 0, "mark": 0} for asset in self.assets
        }

        self.client.add_orderbook_listener(self._on_orderbook)
        self.client.add_mark_listener(self._on_mark)
        self._last_update_log: Dict[str, Dict[str, float]] = {
            asset: {
                "spot": 0.0,
                "perp": 0.0,
                "mark": 0.0,
                "skip": 0.0,
                "ready": 0.0,
                "state": 0.0,
            }
            for asset in self.assets
        }
        self._last_skip_reason: Dict[str, str] = {asset: "" for asset in self.assets}
        self._state_log_interval = 10.0

    async def run_forever(self, stop_event: Optional[asyncio.Event] = None) -> None:
        self._running = True
        logger.info(
            "[SPOT_PERP][INFO] engine_start assets=%s log_every_seconds=%s",
            self.assets,
            self._heartbeat_interval,
        )
        await self.client.start_market_data(self.assets, self.assets, self.assets)

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(stop_event))
        self._feed_health_task = asyncio.create_task(self._feed_health_loop(stop_event))

        try:
            while self._running and (not stop_event or not stop_event.is_set()):
                await asyncio.sleep(1)
        finally:
            self._running = False
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._heartbeat_task
            if self._feed_health_task:
                self._feed_health_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._feed_health_task
            self._log_summary("run_forever_exit")

    def _on_orderbook(self, kind: str, coin: str, ob_norm: Dict[str, Any]) -> None:
        if coin not in self.asset_state:
            return
        ts = float(ob_norm.get("ts") or time.time())
        book = BookSnapshot(best_bid=ob_norm.get("bid") or 0.0, best_ask=ob_norm.get("ask") or 0.0, ts=ts)
        if kind == "perp":
            self.asset_state[coin].perp = book
            if self.update_counts[coin]["perp"] == 0:
                logger.info("[SPOT_PERP][INFO] first_perp_l2_received asset=%s", coin)
            if book.has_liquidity():
                self.update_counts[coin]["perp"] += 1
            if ts - self._last_update_log[coin]["perp"] >= 1:
                self._last_update_log[coin]["perp"] = ts
                logger.debug(
                    "[SPOT_PERP][DEBUG] perp_update asset=%s bid=%.6f ask=%.6f ts=%s",
                    coin,
                    book.best_bid,
                    book.best_ask,
                    ts,
                )
        else:
            self.asset_state[coin].spot = book
            if self.update_counts[coin]["spot"] == 0:
                logger.info("[SPOT_PERP][INFO] first_spot_l2_received asset=%s", coin)
            if book.has_liquidity():
                self.update_counts[coin]["spot"] += 1
            if ts - self._last_update_log[coin]["spot"] >= 1:
                self._last_update_log[coin]["spot"] = ts
                logger.debug(
                    "[SPOT_PERP][DEBUG] spot_update asset=%s bid=%.6f ask=%.6f ts=%s",
                    coin,
                    book.best_bid,
                    book.best_ask,
                    ts,
                )
        self._evaluate_and_record(coin)

    def _on_mark(self, coin: str, mark: float, raw_payload: Dict[str, Any]) -> None:
        if coin not in self.asset_state:
            return
        self.asset_state[coin].mark_price = mark
        self.asset_state[coin].mark_ts = float(raw_payload.get("time") or raw_payload.get("ts") or time.time())
        if self.update_counts[coin]["mark"] == 0:
            logger.info("[SPOT_PERP][INFO] first_mark_received asset=%s", coin)
        self.update_counts[coin]["mark"] += 1
        ts = raw_payload.get("time") or raw_payload.get("ts") or time.time()
        if ts - self._last_update_log[coin]["mark"] >= 1:
            self._last_update_log[coin]["mark"] = ts
            logger.debug(
                "[SPOT_PERP][DEBUG] mark_update asset=%s mark=%.6f ts=%s",
                coin,
                mark,
                ts,
            )
        if raw_payload.get("fundingRate") is not None:
            try:
                self.asset_state[coin].funding_rate = float(raw_payload.get("fundingRate"))
            except Exception:
                pass

    async def _heartbeat_loop(self, stop_event: Optional[asyncio.Event]) -> None:
        while self._running and (not stop_event or not stop_event.is_set()):
            await asyncio.sleep(self._heartbeat_interval)
            self._log_heartbeat()
            if time.time() - self._last_metrics_log >= self._metrics_interval:
                self._last_metrics_log = time.time()
                self._log_metrics()

    async def _feed_health_loop(self, stop_event: Optional[asyncio.Event]) -> None:
        interval = self.feed_health.settings.log_interval_sec if self.feed_health else 1.0
        while self._running and (not stop_event or not stop_event.is_set()):
            await asyncio.sleep(interval)
            self._log_feed_health()

    def _log_heartbeat(self) -> None:
        self._last_heartbeat = time.time()
        for asset, counts in self.update_counts.items():
            state = self.asset_state[asset]
            spot_ok = counts["spot"] > 0 and state.spot.has_liquidity()
            perp_ok = counts["perp"] > 0 and state.perp.has_liquidity()
            mark_ok = counts["mark"] > 0 and state.mark_price > 0
            logger.info(
                (
                    "[SPOT_PERP][INFO] heartbeat asset=%s "
                    "spot_seen=%d perp_seen=%d mark_seen=%d "
                    "spot_ok=%s perp_ok=%s mark_ok=%s"
                ),
                asset,
                counts["spot"],
                counts["perp"],
                counts["mark"],
                spot_ok,
                perp_ok,
                mark_ok,
            )
            now = time.time()
            if now - self._last_update_log[asset]["state"] >= self._state_log_interval:
                self._last_update_log[asset]["state"] = now
                logger.info(
                    (
                        "[SPOT_PERP][STATE] asset=%s spot_bid=%.6f spot_ask=%.6f "
                        "perp_bid=%.6f perp_ask=%.6f mark=%.6f spot_ok=%s perp_ok=%s mark_ok=%s"
                    ),
                    asset,
                    state.spot.best_bid,
                    state.spot.best_ask,
                    state.perp.best_bid,
                    state.perp.best_ask,
                    state.mark_price,
                    spot_ok,
                    perp_ok,
                    mark_ok,
                )
            if spot_ok and perp_ok and mark_ok and (time.time() - self._last_update_log[asset]["ready"] >= 1):
                self._last_update_log[asset]["ready"] = time.time()
                logger.info(
                    "[SPOT_PERP][INFO] data_ready asset=%s spot_ok=%s perp_ok=%s mark_ok=%s",
                    asset,
                    spot_ok,
                    perp_ok,
                    mark_ok,
                )

    def _log_feed_health(self) -> None:
        for asset in self.assets:
            snapshot = self.feed_health.build_asset_snapshot(asset)
            logger.info(
                (
                    "[FEED_HEALTH] asset=%s spot_age_ms=%.1f perp_age_ms=%.1f "
                    "spot_bbo=%.6f/%.6f perp_bbo=%.6f/%.6f "
                    "spot_incomplete=%s perp_incomplete=%s stale=%s crossed=%s out_of_sync=%s "
                    "ws_msgs=%d dup=%d hb=%d book_incomplete=%d stale_book=%d crossed_book=%d out_of_sync_count=%d"
                ),
                asset,
                snapshot["spot_age_ms"],
                snapshot["perp_age_ms"],
                snapshot["spot_bid"],
                snapshot["spot_ask"],
                snapshot["perp_bid"],
                snapshot["perp_ask"],
                snapshot["spot_incomplete"],
                snapshot["perp_incomplete"],
                snapshot["stale"],
                snapshot["crossed"],
                snapshot["out_of_sync"],
                snapshot["ws_msgs_total"],
                snapshot["duplicate_events"],
                snapshot["heartbeat_only"],
                snapshot["book_incomplete"],
                snapshot["stale_book"],
                snapshot["crossed_book"],
                snapshot["out_of_sync_count"],
            )

    def _log_strategy_skip(self, asset: str, reason: str, snapshot: Dict[str, Any]) -> None:
        interval = self.feed_health.settings.log_interval_sec if self.feed_health else 1.0
        now = time.time()
        if reason == self._last_skip_reason[asset] and now - self._last_update_log[asset]["skip"] < interval:
            return
        self._last_skip_reason[asset] = reason
        self._last_update_log[asset]["skip"] = now
        state = self.asset_state[asset]
        logger.info(
            (
                "[STRATEGY_SKIP] asset=%s reason=%s spot_age_ms=%.1f perp_age_ms=%.1f "
                "spot_bbo=%.6f/%.6f perp_bbo=%.6f/%.6f"
            ),
            asset,
            reason,
            snapshot.get("spot_age_ms", float("inf")),
            snapshot.get("perp_age_ms", float("inf")),
            state.spot.best_bid,
            state.spot.best_ask,
            state.perp.best_bid,
            state.perp.best_ask,
        )

    def _log_metrics(self) -> None:
        reconnect_counts = getattr(self.client, "reconnect_counts", {})
        logger.info(
            (
                "[SPOT_PERP][METRICS] interval=%ss opportunities_seen=%d trades_executed=%d "
                "pnl_est=%.4f drawdown=%.4f ws_reconnects=%s"
            ),
            self._metrics_interval,
            self.opportunities_seen,
            self.trades_executed,
            self.pnl_estimated,
            self.max_drawdown,
            reconnect_counts,
        )
        for asset, state in self.asset_state.items():
            logger.info(
                (
                    "[SPOT_PERP][LAST_PRICES] asset=%s spot_bid=%.6f spot_ask=%.6f perp_bid=%.6f "
                    "perp_ask=%.6f mark=%.6f mark_ok=%s"
                ),
                asset,
                state.spot.best_bid,
                state.spot.best_ask,
                state.perp.best_bid,
                state.perp.best_ask,
                state.mark_price,
                state.mark_price > 0,
            )

    def _evaluate_and_record(self, asset: str) -> None:
        state = self.asset_state[asset]
        snapshot = self.feed_health.build_asset_snapshot(asset)
        reason: Optional[str] = None

        if state.mark_price <= 0:
            reason = "SKIP_NO_BOOK"
        elif not state.spot.has_liquidity() or not state.perp.has_liquidity():
            reason = "SKIP_NO_BOOK"
        elif snapshot["spot_incomplete"] or snapshot["perp_incomplete"]:
            reason = "SKIP_INCOMPLETE"
        elif snapshot["stale"]:
            reason = "SKIP_STALE"
        elif snapshot["out_of_sync"]:
            reason = "SKIP_OUT_OF_SYNC"
        elif snapshot["crossed"]:
            reason = "SKIP_INVALID_BBO"

        if reason:
            self._log_strategy_skip(asset, reason, snapshot)
            return

        spot = state.spot
        perp = state.perp
        notional = max(self.trading.min_position_size, 1.0)
        funding_estimate = state.funding_rate * notional

        spread_long = (
            (perp.best_bid - spot.best_ask) / spot.best_ask if spot.best_ask > 0 else float("-inf")
        )
        spread_short = (
            (spot.best_bid - perp.best_ask) / spot.best_bid if perp.best_ask > 0 else float("-inf")
        )

        if spread_long >= spread_short:
            spread_gross = spread_long
            direction = "spot_long"
            spot_px = spot.best_ask
            perp_px = perp.best_bid
            spot_label = "spot_ask"
            perp_label = "perp_bid"
        else:
            spread_gross = spread_short
            direction = "spot_short"
            spot_px = spot.best_bid
            perp_px = perp.best_ask
            spot_label = "spot_bid"
            perp_label = "perp_ask"

        fee_spot = self.taker_fee_spot * notional
        fee_perp = self.taker_fee_perp * notional
        pnl_net = spread_gross * notional - fee_spot - fee_perp - funding_estimate

        logger.info(
            "[SPOT_PERP][INFO] compute_attempt asset=%s spot_price=%.6f perp_price=%.6f mark=%.6f "
            "spread_gross=%+.6f pnl_net_est=%+.6f",
            asset,
            spot_px,
            perp_px,
            state.mark_price,
            spread_gross,
            pnl_net,
        )

        if spread_gross <= 0 or pnl_net <= 0:
            return

        fee_total = fee_spot + fee_perp
        self._log_opportunity(
            asset=asset,
            direction=direction,
            spot_price=spot_px,
            perp_price=perp_px,
            mark_price=state.mark_price,
            spot_label=spot_label,
            perp_label=perp_label,
            spread_gross=spread_gross,
            fee_total=fee_total,
            funding_estimate=funding_estimate,
            pnl_net_estimated=pnl_net,
        )
        self._persist_opportunity(
            asset=asset,
            direction=direction,
            spot_price=spot_px,
            perp_price=perp_px,
            mark_price=state.mark_price,
            spread_gross=spread_gross,
            fee_estimated=fee_total,
            funding_estimated=funding_estimate,
            pnl_net_estimated=pnl_net,
        )

    def _log_opportunity(
        self,
        asset: str,
        direction: str,
        spot_price: float,
        perp_price: float,
        mark_price: float,
        spot_label: str,
        perp_label: str,
        spread_gross: float,
        fee_total: float,
        funding_estimate: float,
        pnl_net_estimated: float,
    ) -> None:
        logger.info(
            (
                "[SPOT_PERP]\n"
                "asset=%s\n"
                "%s=%.6f\n"
                "%s=%.6f\n"
                "mark=%.6f\n"
                "spread_gross=%+.2f%%\n"
                "fee_total=%.4f\n"
                "funding_est=%.4f\n"
                "pnl_net_est=%+.4f\n"
                "direction=%s"
            ),
            asset,
            spot_label,
            spot_price,
            perp_label,
            perp_price,
            mark_price,
            spread_gross * 100,
            fee_total,
            funding_estimate,
            pnl_net_estimated,
            direction,
        )

    def _persist_opportunity(
        self,
        asset: str,
        direction: str,
        spot_price: float,
        perp_price: float,
        mark_price: float,
        spread_gross: float,
        fee_estimated: float,
        funding_estimated: float,
        pnl_net_estimated: float,
    ) -> None:
        session = self.db_session_factory()
        with session as s:
            s.add(
                SpotPerpOpportunity(
                    timestamp=time.time(),
                    asset=asset,
                    direction=direction,
                    spot_price=spot_price,
                    perp_price=perp_price,
                    mark_price=mark_price,
                    spread_gross=spread_gross,
                    fee_estimated=fee_estimated,
                    funding_estimated=funding_estimated,
                    pnl_net_estimated=pnl_net_estimated,
                )
            )
            s.commit()
        self.opportunities_seen += 1
        self.trades_executed += 1
        self.pnl_estimated += pnl_net_estimated
        self._pnl_peak = max(self._pnl_peak, self.pnl_estimated)
        self.max_drawdown = max(self.max_drawdown, self._pnl_peak - self.pnl_estimated)

    async def shutdown(self) -> None:
        """Stop background loops and emit a final summary for observability."""

        self._running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
        if self._feed_health_task and not self._feed_health_task.done():
            self._feed_health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._feed_health_task
        self._log_summary()

    def _log_summary(self, reason: str = "shutdown") -> None:
        logger.info(
            (
                "[SPOT_PERP][SUMMARY] reason=%s opportunities_seen=%d trades_executed=%d "
                "pnl_est=%.4f max_drawdown=%.4f ws_reconnects=%s"
            ),
            reason,
            self.opportunities_seen,
            self.trades_executed,
            self.pnl_estimated,
            self.max_drawdown,
            getattr(self.client, "reconnect_counts", {}),
        )
        for asset, state in self.asset_state.items():
            logger.info(
                (
                    "[SPOT_PERP][SUMMARY_PRICES] asset=%s spot_bid=%.6f spot_ask=%.6f "
                    "perp_bid=%.6f perp_ask=%.6f mark=%.6f"
                ),
                asset,
                state.spot.best_bid,
                state.spot.best_ask,
                state.perp.best_bid,
                state.perp.best_ask,
                state.mark_price,
            )


async def run_spot_perp_engine(
    assets: Iterable[str],
    settings: Optional[Settings] = None,
    taker_fee_spot: float = 0.001,
    taker_fee_perp: float = 0.0005,
):  
    settings = settings or load_config("config/config.yaml")
    feed_health_settings = settings.observability.feed_health
    feed_health_tracker = FeedHealthTracker(feed_health_settings)
    client = HyperliquidClient(settings.api, settings.network, feed_health_tracker=feed_health_tracker)
    db_session_factory = get_session(settings)
    engine = SpotPerpPaperEngine(
        client,
        assets,
        settings.trading,
        db_session_factory=db_session_factory,
        taker_fee_spot=taker_fee_spot,
        taker_fee_perp=taker_fee_perp,
        feed_health_settings=feed_health_settings,
        feed_health_tracker=feed_health_tracker,
    )
    stop_event = asyncio.Event()

    try:
        await engine.run_forever(stop_event=stop_event)
    finally:
        stop_event.set()
        await client.close()
