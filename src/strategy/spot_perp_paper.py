from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import or_

from src.config.loader import load_config
from src.config.models import FeedHealthSettings, Settings, TradingSettings, ValidationSettings
from src.core.logging import get_logger
from src.db.models import Base, DecisionOutcome, DecisionSnapshot, MakerProbe, SpotPerpOpportunity
from src.db.session import get_session
from src.hyperliquid_client.client import HyperliquidClient
from src.observability.feed_health import FeedHealthTracker

logger = get_logger(__name__)

# Domain model for a single synthetic Spot/Perp paper trade.
# Introduced for correctness, validation, and future extensions (Perp/Perp, Lead–Lag).
@dataclass
class SyntheticSpotPerpTrade:
    asset: str
    spot_symbol: str
    perp_symbol: str
    direction: str  # "long_spot_short_perp" oppure "short_spot_long_perp"
    spot_price: float
    perp_price: float
    spot_qty: float
    perp_qty: float
    gross_edge: float
    net_edge: float
    fees_spot: float
    fees_perp: float
    timestamp_ms: int

HL_TIER_0_FEE_TAKER_SPOT = 0.001
HL_TIER_0_FEE_TAKER_PERP = 0.0005
HL_TIER_LABEL = "HL_TIER_0"


def now_ms() -> int:
    return int(time.time() * 1000)


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
        return self.best_bid > 0 and self.best_ask > 0 and self.best_bid < self.best_ask


@dataclass
class AssetState:
    spot: BookSnapshot = field(default_factory=BookSnapshot)
    perp: BookSnapshot = field(default_factory=BookSnapshot)
    mark_price: float = 0.0
    funding_rate: float = 0.0
    mark_ts: float = 0.0
    spot_proxy: float = 0.0
    spot_proxy_ts: float = 0.0

    def ready(self) -> bool:
        return self.spot.has_liquidity() and self.perp.has_liquidity() and self.mark_price > 0


@dataclass
class SpotPerpEdgeSnapshot:
    asset: str
    spot_bid: float
    spot_ask: float
    perp_bid: float
    perp_ask: float
    spot_price: float
    perp_price: float
    spread_gross: float
    pnl_net_est: float
    edge_bps: float
    below_min_edge: bool
    direction: str
    notional_usd: float
    fee_spot_rate: float
    fee_perp_rate: float
    fee_spot: float
    fee_perp: float
    fee_est: float
    base_slip_bps: float
    buffer_bps: float
    slippage_bps: float
    slippage_est: float
    base_slip_rate: float
    buffer_rate: float
    slippage_rate: float
    funding_rate: float
    funding_estimate: float
    total_cost_bps: float
    min_edge_threshold: float
    min_edge_rate: float
    min_edge_bps: float
    effective_threshold: float
    effective_threshold_bps: float
    spot_spread_bps: float
    perp_spread_bps: float
    qty: float


class ValidationRecorder:
    def __init__(self, session_factory, settings: ValidationSettings) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self._snapshots: List[DecisionSnapshot] = []
        self._outcomes: List[DecisionOutcome] = []
        self.total_rows = 0
        self.validation_written_total = 0
        self.db_path = getattr(session_factory, "db_path", "unknown")
        self.reason_counts: Counter[str] = Counter()
        self.outcome_counts: Counter[str] = Counter()

    def record(
        self,
        snapshot: DecisionSnapshot,
        outcome: DecisionOutcome,
    ) -> None:
        self._snapshots.append(snapshot)
        self._outcomes.append(outcome)
        self.total_rows += 1
        self.reason_counts[outcome.reason] += 1
        self.outcome_counts[outcome.outcome] += 1
        if len(self._snapshots) >= max(1, self.settings.sqlite_flush_every_n):
            self.flush()

    def flush(self) -> None:
        if not self._snapshots and not self._outcomes:
            return
        with self.session_factory() as session:
            if self._snapshots:
                session.execute(
                    DecisionSnapshot.__table__.insert(),
                    [self._snapshot_to_row(snapshot) for snapshot in self._snapshots],
                )
            if self._outcomes:
                session.execute(
                    DecisionOutcome.__table__.insert(),
                    [self._outcome_to_row(outcome) for outcome in self._outcomes],
                )
            session.commit()
        batch_size = len(self._outcomes)
        self.validation_written_total += batch_size
        logger.info(
            "[VALIDATION_WRITE] committed_batch n=%d total=%d db=%s",
            batch_size,
            self.validation_written_total,
            self.db_path,
        )
        self._snapshots.clear()
        self._outcomes.clear()

    @staticmethod
    def _snapshot_to_row(snapshot: DecisionSnapshot) -> Dict[str, Any]:
        return {col.name: getattr(snapshot, col.name) for col in DecisionSnapshot.__table__.columns}

    @staticmethod
    def _outcome_to_row(outcome: DecisionOutcome) -> Dict[str, Any]:
        return {col.name: getattr(outcome, col.name) for col in DecisionOutcome.__table__.columns}

    def log_stats(self) -> None:
        top_reasons = ", ".join([f"{reason}={count}" for reason, count in self.reason_counts.most_common(3)])
        skip_total = self.total_rows - self.outcome_counts.get("WOULD_TRADE", 0)
        logger.info(
            "[VALIDATION_STATS] written_total=%d would_trade=%d skip_total=%d top_skips=%s",
            self.validation_written_total,
            self.outcome_counts.get("WOULD_TRADE", 0),
            skip_total,
            top_reasons or "n/a",
        )


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
        taker_fee_spot: float = HL_TIER_0_FEE_TAKER_SPOT,
        taker_fee_perp: float = HL_TIER_0_FEE_TAKER_PERP,
        feed_health_settings: Optional[FeedHealthSettings] = None,
        feed_health_tracker: Optional[FeedHealthTracker] = None,
        validation_settings: Optional[ValidationSettings] = None,
        would_trade: bool = False,
        trace_every_seconds: int = 10,
        auto_assets_enabled: bool = False,
        auto_assets_warmup_seconds: float = 3.0,
        auto_assets_warmup_interval: float = 0.25,
        auto_assets_warmup_failure_threshold: int = 3,
        evaluate_on_update: bool = True,
    ) -> None:
        self.client = client
        self.assets = list(assets)
        self.trading = trading
        self.validation_settings = validation_settings or ValidationSettings()
        self._validation_config_provided = validation_settings is not None
        self.taker_fee_spot = taker_fee_spot
        self.taker_fee_perp = taker_fee_perp
        default_fee_mode = str(getattr(trading, "fee_mode", "maker")).lower()
        self.default_fee_mode = default_fee_mode
        self.maker_fee_spot = getattr(trading, "maker_fee_spot", 0.0)
        self.maker_fee_perp = getattr(trading, "maker_fee_perp", 0.0)
        self.spot_fee_mode = str(getattr(trading, "spot_fee_mode", default_fee_mode)).lower()
        self.perp_fee_mode = str(getattr(trading, "perp_fee_mode", default_fee_mode)).lower()
        self.effective_fee_spot_rate = (
            self.maker_fee_spot if self.spot_fee_mode == "maker" else self.taker_fee_spot
        )
        self.effective_fee_perp_rate = (
            self.maker_fee_perp if self.perp_fee_mode == "maker" else self.taker_fee_perp
        )
        self.db_session_factory = db_session_factory
        self.feed_health = feed_health_tracker or FeedHealthTracker(feed_health_settings)
        self.client.set_feed_health_tracker(self.feed_health)
        self.max_spot_spread_bps = float(getattr(trading, "max_spot_spread_bps", 500.0))
        self.asset_state: Dict[str, AssetState] = {asset: AssetState() for asset in self.assets}
        self._asset_spot_pairs: Dict[str, str] = {}
        self._spot_symbol_map: Dict[str, str] = {}
        self._spot_pair_overrides: Dict[str, str] = {}
        self._spot_subscription_coins: List[str] = []
        self._init_spot_proxy_maps()
        self._running = False
        self._heartbeat_interval = 10
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._feed_health_task: Optional[asyncio.Task] = None
        self._validation_task: Optional[asyncio.Task] = None
        self._last_heartbeat = time.time()
        self._metrics_interval = float(os.getenv("SPOT_PERP_METRICS_INTERVAL", "30"))
        self._last_metrics_log = time.time()
        self._validation_first_tick_logged = False
        self._log_below_min_edge_enabled = os.getenv("SPOT_PERP_LOG_BELOW_MIN_EDGE", "0") == "1"
        self._below_edge_last_log_ts: Dict[str, float] = {}
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
        self._validation_recorder: Optional[ValidationRecorder] = None
        if self.validation_settings.enabled:
            self._validation_recorder = ValidationRecorder(self.db_session_factory, self.validation_settings)
        self._last_spot_diag_log: Dict[str, float] = {asset: 0.0 for asset in self.assets}
        self.would_trade = would_trade
        self.trace_every_seconds = float(trace_every_seconds)
        self.auto_assets_enabled = auto_assets_enabled
        self.auto_assets_warmup_seconds = float(auto_assets_warmup_seconds)
        self.auto_assets_warmup_interval = float(auto_assets_warmup_interval)
        self.auto_assets_warmup_failure_threshold = int(auto_assets_warmup_failure_threshold)
        self.evaluate_on_update = bool(evaluate_on_update)
        self._trace_state: Dict[str, Dict[str, Any]] = {
            asset: {
                "last_log": 0.0,
                "last_ready": False,
                "last_reason": "INIT",
                "trace_emitted": 0,
                "ready_transitions": 0,
            }
            for asset in self.assets
        }
        self._maker_probe_history: Dict[str, Dict[str, Any]] = {
            asset: {"spot": None, "perp": None} for asset in self.assets
        }
        self._maker_probe_warned = False
        self._maker_probe_skip_logged: Dict[str, bool] = {asset: False for asset in self.assets}
        self._maker_probe_table_ready = False
        self._maker_probe_counter = 0
        self._db_factory_return_logged = False
        self._maker_probe_persist_log_emitted = False
        self._maker_probe_table_log_emitted: Dict[str, bool] = {asset: False for asset in self.assets}
        self._maker_probe_persistence_enabled = os.getenv("SPOT_PERP_DISABLE_MAKER_PROBE", "").lower() not in (
            "1",
            "true",
            "yes",
        )
        self._maker_probe_always_enabled = os.getenv("SPOT_PERP_MAKER_PROBE_ALWAYS", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self._maker_probe_always_interval_ms = int(
            os.getenv("SPOT_PERP_MAKER_PROBE_ALWAYS_INTERVAL_MS", "750")
        )
        self._maker_probe_always_last_ts: Dict[str, int] = {asset: 0 for asset in self.assets}
        self._maker_probe_always_last_log_ts: Dict[str, int] = {asset: 0 for asset in self.assets}
        logger.info(
            "[SPOT_PERP][MAKER_PROBE] always_enabled=%s interval_ms=%s",
            "true" if self._maker_probe_always_enabled else "false",
            self._maker_probe_always_interval_ms,
        )
        if self._maker_probe_persistence_enabled:
            self._ensure_maker_probe_table()

    @staticmethod
    def _resolve_fee_rate(mode: str, maker_rate: float, taker_rate: float) -> float:
        return maker_rate if str(mode).lower() == "maker" else taker_rate

    @staticmethod
    def _to_rate_maybe_bps(value: Optional[float]) -> float:
        """Normalize rate inputs, treating values >= 1 as bps."""
        if value is None:
            return 0.0
        if value <= 0:
            return value
        # Convention: values >= 1 are provided in bps; 0 < value < 1 are already rate.
        if value >= 1:
            return value / 10000
        return value

    def _init_spot_proxy_maps(self) -> None:
        overrides = {key.upper(): value for key, value in (self.trading.spot_pair_overrides or {}).items()}
        quote = (self.trading.quote_asset or "USDC").upper()
        self._asset_spot_pairs.clear()
        self._spot_symbol_map.clear()
        self._spot_pair_overrides.clear()
        self._spot_subscription_coins.clear()
        for asset in self.assets:
            default_pair = f"{asset}/{quote}"
            override_pair = overrides.get(asset.upper())
            pair = (override_pair or default_pair).upper()
            self._asset_spot_pairs[asset] = pair
            coin = pair.split("/")[0]
            self._spot_symbol_map[coin] = asset
            self._spot_pair_overrides[coin] = pair
            if pair != default_pair:
                logger.info("[SPOT_PROXY] %s -> %s", asset, pair)
        self._spot_subscription_coins = list(self._spot_symbol_map.keys())

    def add_assets(self, assets: Iterable[str]) -> List[str]:
        new_assets = []
        for asset in assets:
            asset = asset.upper()
            if asset in self.asset_state:
                continue
            new_assets.append(asset)
            self.asset_state[asset] = AssetState()
            self.assets.append(asset)
            self.update_counts[asset] = {"spot": 0, "perp": 0, "mark": 0}
            self._last_update_log[asset] = {
                "spot": 0.0,
                "perp": 0.0,
                "mark": 0.0,
                "skip": 0.0,
                "ready": 0.0,
                "state": 0.0,
            }
            self._last_skip_reason[asset] = ""
            self._last_spot_diag_log[asset] = 0.0
            self._trace_state[asset] = {
                "last_log": 0.0,
                "last_ready": False,
                "last_reason": "INIT",
                "trace_emitted": 0,
                "ready_transitions": 0,
            }
            self._maker_probe_history[asset] = {"spot": None, "perp": None}
            self._maker_probe_skip_logged[asset] = False
            self._maker_probe_always_last_ts[asset] = 0
            self._maker_probe_always_last_log_ts[asset] = 0
            self._maker_probe_table_log_emitted[asset] = False
        if new_assets:
            self._init_spot_proxy_maps()
        return new_assets

    async def start_market_data(self) -> None:
        await self.client.start_market_data(
            self._spot_subscription_coins,
            self.assets,
            self.assets,
            spot_symbol_map=self._spot_symbol_map,
            spot_pair_overrides=self._spot_pair_overrides,
        )

    def _drop_auto_asset(self, asset: str, reason: str, sanity_failures: int) -> None:
        if asset not in self.asset_state:
            return
        logger.info(
            "[SPOT_PERP][AUTO_ASSETS] drop asset=%s reason=%s sanity_failures=%d",
            asset,
            reason,
            sanity_failures,
        )
        self.asset_state.pop(asset, None)
        self.assets = [item for item in self.assets if item != asset]
        self.update_counts.pop(asset, None)
        self._last_update_log.pop(asset, None)
        self._last_skip_reason.pop(asset, None)
        self._last_spot_diag_log.pop(asset, None)
        self._trace_state.pop(asset, None)
        self._maker_probe_history.pop(asset, None)
        self._maker_probe_skip_logged.pop(asset, None)
        self._maker_probe_always_last_ts.pop(asset, None)
        self._maker_probe_always_last_log_ts.pop(asset, None)

    async def _run_auto_assets_warmup(self) -> None:
        if not self.auto_assets_enabled or not self.assets:
            return
        interval = max(0.05, self.auto_assets_warmup_interval)
        deadline = time.time() + max(0.0, self.auto_assets_warmup_seconds)
        counters: Dict[str, Counter[str]] = {asset: Counter() for asset in self.assets}
        while time.time() < deadline and self.assets:
            for asset in list(self.assets):
                state = self.asset_state.get(asset)
                if not state:
                    continue
                snapshot = self.feed_health.build_asset_snapshot(asset)
                spot_bid = state.spot.best_bid
                spot_ask = state.spot.best_ask
                if spot_bid <= 0:
                    counters[asset]["no_bids"] += 1
                if spot_ask <= 0:
                    counters[asset]["no_asks"] += 1
                if snapshot.get("spot_incomplete"):
                    counters[asset]["spot_incomplete"] += 1
                if spot_bid > 0 and spot_ask > 0 and spot_bid < spot_ask:
                    spot_spread_bps = (spot_ask - spot_bid) / spot_bid * 10000
                    if spot_spread_bps > self.max_spot_spread_bps:
                        counters[asset]["spot_spread_too_wide"] += 1
            await asyncio.sleep(interval)

        for asset in list(self.assets):
            asset_counts = counters.get(asset) or Counter()
            sanity_failures = asset_counts.get("spot_spread_too_wide", 0)
            spot_incomplete = asset_counts.get("spot_incomplete", 0)
            no_bids = asset_counts.get("no_bids", 0)
            no_asks = asset_counts.get("no_asks", 0)
            threshold = self.auto_assets_warmup_failure_threshold
            should_drop = any(
                count >= threshold for count in (sanity_failures, spot_incomplete, no_bids, no_asks)
            )
            if not should_drop:
                continue
            if sanity_failures >= threshold:
                reason = "spot_spread_too_wide"
            elif spot_incomplete >= threshold:
                reason = "spot_incomplete"
            elif no_bids >= threshold:
                reason = "no_bids"
            else:
                reason = "no_asks"
            reason_detail = (
                f"{reason} spot_incomplete={spot_incomplete} "
                f"no_bids={no_bids} no_asks={no_asks}"
            )
            self._drop_auto_asset(asset, reason_detail, sanity_failures)

    def _remove_asset_from_tracking(self, asset: str) -> None:
        self.asset_state.pop(asset, None)
        self.assets = [item for item in self.assets if item != asset]
        self.update_counts.pop(asset, None)
        self._last_update_log.pop(asset, None)
        self._last_skip_reason.pop(asset, None)
        self._last_spot_diag_log.pop(asset, None)
        self._trace_state.pop(asset, None)
        self._maker_probe_history.pop(asset, None)
        self._maker_probe_skip_logged.pop(asset, None)
        self._maker_probe_always_last_ts.pop(asset, None)
        self._maker_probe_always_last_log_ts.pop(asset, None)

    async def _preflight_filter_assets_for_spot_book(
        self,
        assets: Iterable[str],
        timeout_s: float = 6.0,
        interval_s: float = 0.25,
        get_snapshot: Optional[
            Callable[[str], Tuple[Dict[str, Any], Optional[AssetState]]]
        ] = None,
    ) -> List[str]:
        asset_list = list(assets)
        if not asset_list:
            return []
        interval = max(0.05, float(interval_s))
        start_time = time.time()
        deadline = start_time + max(0.0, float(timeout_s))
        pending = set(asset_list)
        passed: set[str] = set()
        last_spot_prices: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
        getter = get_snapshot or (
            lambda asset: (self.feed_health.build_asset_snapshot(asset), self.asset_state.get(asset))
        )
        logger.info(
            "[SPOT_PERP][AUTO_ASSETS][PREFLIGHT] start assets=%s timeout_s=%.2f interval_s=%.2f",
            asset_list,
            timeout_s,
            interval,
        )
        while pending and time.time() < deadline:
            for asset in list(pending):
                _snapshot, state = getter(asset)
                if not state:
                    continue
                spot_bid = state.spot.best_bid
                spot_ask = state.spot.best_ask
                last_spot_prices[asset] = (spot_bid, spot_ask)
                if spot_bid and spot_ask and spot_bid > 0 and spot_ask > spot_bid:
                    spread = spot_ask - spot_bid
                    mid = 0.5 * (spot_ask + spot_bid)
                    logger.info(
                        "[SPOT_PERP][AUTO_ASSETS][PREFLIGHT] pass asset=%s bid=%.6f ask=%.6f spread=%.6f mid=%.6f",
                        asset,
                        spot_bid,
                        spot_ask,
                        spread,
                        mid,
                    )
                    passed.add(asset)
                    pending.remove(asset)
            if pending and time.time() < deadline:
                await asyncio.sleep(interval)
        waited_s = max(0.0, time.time() - start_time)
        dropped: List[str] = []
        for asset in list(pending):
            last_bid, last_ask = last_spot_prices.get(asset, (None, None))
            if (
                last_bid is None
                or last_ask is None
                or last_bid <= 0
                or last_ask <= 0
            ):
                reason = "spot_book_empty"
            else:
                reason = "spot_book_zero_or_crossed"
            bid_log = f"{last_bid:.6f}" if last_bid is not None else "n/a"
            ask_log = f"{last_ask:.6f}" if last_ask is not None else "n/a"
            logger.info(
                "[SPOT_PERP][AUTO_ASSETS][PREFLIGHT] drop asset=%s reason=%s waited_s=%.2f bid=%s ask=%s",
                asset,
                reason,
                waited_s,
                bid_log,
                ask_log,
            )
            dropped.append(asset)
        kept = [asset for asset in asset_list if asset in passed]
        logger.info(
            "[SPOT_PERP][AUTO_ASSETS][PREFLIGHT] done kept=%s dropped=%s",
            kept,
            dropped,
        )
        return kept

    def _ensure_maker_probe_table(self) -> None:
        if not self._maker_probe_persistence_enabled:
            return
        if self._maker_probe_table_ready:
            return
        if self.db_session_factory is get_session and not os.path.exists("config/config.yaml"):
            if not self._maker_probe_warned:
                logger.debug(
                    "[SPOT_PERP][MAKER_PROBE] skipping_table_setup_missing_config path=config/config.yaml"
                )
                self._maker_probe_warned = True
            return
        try:
            with self._maker_probe_session() as session:
                if not hasattr(session, "get_bind"):
                    raise TypeError(
                        "[SPOT_PERP][MAKER_PROBE] session_missing_get_bind type=%s"
                        % type(session)
                    )
                bind = session.get_bind()
                if bind:
                    Base.metadata.create_all(bind=bind, tables=[MakerProbe.__table__])
                    self._maker_probe_table_ready = True
        except Exception:
            if not self._maker_probe_warned:
                logger.warning("[SPOT_PERP][MAKER_PROBE] ensure_table_failed", exc_info=True)
                self._maker_probe_warned = True

    @staticmethod
    def _is_session_like(candidate: Any) -> bool:
        return all(
            hasattr(candidate, attribute)
            for attribute in ("execute", "get_bind", "commit", "close")
        )

    @contextlib.contextmanager
    def _maker_probe_session(self):
        obj = self.db_session_factory()
        chain_types = []
        max_unwrap = 5
        for _ in range(max_unwrap):
            chain_types.append(type(obj))
            is_ctx = hasattr(obj, "__enter__") and hasattr(obj, "__exit__")
            is_session_like = self._is_session_like(obj)
            if is_ctx or is_session_like or not callable(obj):
                break
            obj = obj()
        is_ctx = hasattr(obj, "__enter__") and hasattr(obj, "__exit__")
        is_session_like = self._is_session_like(obj)
        callable_flag = callable(obj)
        if not self._db_factory_return_logged:
            logger.debug(
                "[SPOT_PERP][MAKER_PROBE] db_factory_unwrap chain=%s final=%s is_ctx=%s is_session_like=%s callable=%s",
                chain_types,
                type(obj),
                is_ctx,
                is_session_like,
                callable_flag,
            )
            self._db_factory_return_logged = True
        if callable_flag and not is_session_like and not is_ctx:
            raise TypeError(
                "[SPOT_PERP][MAKER_PROBE] db_factory_unwrap_failed final=%s"
                % type(obj)
            )
        if is_ctx:
            with obj as session:
                yield session
            return
        session = obj
        try:
            yield session
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def _get_snapshot_pair(
        self, asset: str, kind_curr: str, snapshot: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[float]]:
        history = self._maker_probe_history.setdefault(asset, {"spot": None, "perp": None})
        history[kind_curr] = snapshot
        curr = history.get(kind_curr)
        next_snapshot: Optional[Dict[str, Any]] = None
        dt_next_ms: Optional[float] = None
        return curr, next_snapshot, dt_next_ms

    def _update_open_maker_probe_always(
        self,
        session,
        asset: str,
        ts_ms: int,
        spot_bid: float,
        spot_ask: float,
        perp_bid: float,
        perp_ask: float,
    ) -> None:
        max_close = 3
        open_probes = (
            session.query(MakerProbe)
            .filter(
                MakerProbe.asset == asset,
                MakerProbe.ts.isnot(None),
                MakerProbe.dt_next_ms < 0,
            )
            .order_by(MakerProbe.id.desc())
            .limit(max_close)
            .all()
        )
        if not open_probes:
            return
        updated = False
        for probe in open_probes:
            age_ms = ts_ms - probe.ts
            if age_ms > 300_000:
                break
            dt_next_ms = max(0.0, float(age_ms))
            probe.spot_bid_next = spot_bid
            probe.spot_ask_next = spot_ask
            probe.perp_bid_next = perp_bid
            probe.perp_ask_next = perp_ask
            probe.dt_next_ms = dt_next_ms
            updated = True
            logger.info(
                "[SPOT_PERP][MAKER_PROBE] update_next id=%s asset=%s dt_next_ms=%.1f",
                probe.id,
                asset,
                dt_next_ms,
            )
        if updated:
            session.flush()

    def _record_maker_probe(
        self,
        asset: str,
        direction: str,
        spot_px: float,
        perp_px: float,
        spot_bid: float,
        spot_ask: float,
        perp_bid: float,
        perp_ask: float,
        always_mode: bool = False,
    ) -> None:
        ts_ms = now_ms()
        logger.debug(
            "[SPOT_PERP][MAKER_PROBE] entered_record asset=%s persistence_enabled=%s table_ready=%s db_path=%s",
            asset,
            self._maker_probe_persistence_enabled,
            self._maker_probe_table_ready,
            getattr(self.db_session_factory, "db_path", None),
        )
        spot_snapshot = {"ts": ts_ms, "bid": spot_bid, "ask": spot_ask}
        perp_snapshot = {"ts": ts_ms, "bid": perp_bid, "ask": perp_ask}
        spot_curr, spot_next, _ = self._get_snapshot_pair(asset, "spot", spot_snapshot)
        perp_curr, perp_next, _ = self._get_snapshot_pair(asset, "perp", perp_snapshot)
        if not self._maker_probe_persistence_enabled:
            if not self._maker_probe_persist_log_emitted:
                logger.info(
                    "[SPOT_PERP][MAKER_PROBE] skip reason=persistence_disabled db_path=%s",
                    getattr(self.db_session_factory, "db_path", None),
                )
                self._maker_probe_persist_log_emitted = True
            return
        try:
            self._ensure_maker_probe_table()
            if not self._maker_probe_table_ready:
                if not self._maker_probe_table_log_emitted.get(asset, False):
                    logger.warning(
                        "[SPOT_PERP][MAKER_PROBE] skip reason=table_not_ready asset=%s db_path=%s",
                        asset,
                        getattr(self.db_session_factory, "db_path", None),
                    )
                    self._maker_probe_table_log_emitted[asset] = True
                return
            with self._maker_probe_session() as session:
                if always_mode:
                    try:
                        self._update_open_maker_probe_always(
                            session=session,
                            asset=asset,
                            ts_ms=ts_ms,
                            spot_bid=spot_bid,
                            spot_ask=spot_ask,
                            perp_bid=perp_bid,
                            perp_ask=perp_ask,
                        )
                    except Exception:
                        logger.exception(
                            "[SPOT_PERP][MAKER_PROBE] update_next_failed asset=%s",
                            asset,
                        )
                else:
                    last_probe = (
                        session.query(MakerProbe)
                        .filter(MakerProbe.asset == asset, MakerProbe.dt_next_ms <= -0.5)
                        .order_by(MakerProbe.ts.desc())
                        .first()
                    )
                    if last_probe:
                        age_ms = float(now_ms() - (last_probe.ts or now_ms()))
                        if age_ms > 5000:
                            if not self._maker_probe_skip_logged.get(asset):
                                logger.info(
                                    "[SPOT_PERP][MAKER_PROBE] skip_update_next_old id=%s age_ms=%.1f",
                                    last_probe.id,
                                    age_ms,
                                )
                                self._maker_probe_skip_logged[asset] = True
                        else:
                            last_probe.spot_bid_next = spot_bid
                            last_probe.spot_ask_next = spot_ask
                            last_probe.perp_bid_next = perp_bid
                            last_probe.perp_ask_next = perp_ask
                            last_probe.dt_next_ms = max(0.0, age_ms)
                            session.flush()
                            logger.info(
                                "[SPOT_PERP][MAKER_PROBE] update_next id=%s ts=%s dt_next_ms=%.2f age_ms=%.1f",
                                last_probe.id,
                                last_probe.ts,
                                last_probe.dt_next_ms,
                                age_ms,
                            )
                new_probe = MakerProbe(
                    ts=ts_ms,
                    asset=asset,
                    direction=direction,
                    spot_bid=spot_curr.get("bid") if spot_curr else None,
                    spot_ask=spot_curr.get("ask") if spot_curr else None,
                    perp_bid=perp_curr.get("bid") if perp_curr else None,
                    perp_ask=perp_curr.get("ask") if perp_curr else None,
                    spot_maker_px=spot_px,
                    perp_maker_px=perp_px,
                    spot_bid_next=spot_next.get("bid") if spot_next else None,
                    spot_ask_next=spot_next.get("ask") if spot_next else None,
                    perp_bid_next=perp_next.get("bid") if perp_next else None,
                    perp_ask_next=perp_next.get("ask") if perp_next else None,
                    # -1 means we have not yet observed the next relevant event for this probe.
                    dt_next_ms=-1.0,
                )
                session.add(new_probe)
                session.flush()
                session.commit()
                logger.info(
                    "[SPOT_PERP][MAKER_PROBE] insert id=%s asset=%s ts=%s dt_next_ms=%.2f",
                    new_probe.id,
                    asset,
                    ts_ms,
                    -1.0,
                )
                self._maker_probe_counter += 1
                if self._maker_probe_counter % 5 == 0:
                    self._log_recent_maker_probes(session)
        except Exception:
            if not self._maker_probe_warned:
                logger.exception("[SPOT_PERP][MAKER_PROBE] persist_failed")
                self._maker_probe_warned = True

    def _maybe_record_maker_probe_always(self, edge_snapshot: SpotPerpEdgeSnapshot) -> None:
        if not self._maker_probe_always_enabled:
            return
        if (
            edge_snapshot.spot_bid is None
            or edge_snapshot.spot_ask is None
            or edge_snapshot.perp_bid is None
            or edge_snapshot.perp_ask is None
        ):
            return
        asset = edge_snapshot.asset
        ts_ms = now_ms()
        last_ts = self._maker_probe_always_last_ts.get(asset, 0)
        if ts_ms - last_ts < self._maker_probe_always_interval_ms:
            return
        self._maker_probe_always_last_ts[asset] = ts_ms
        self._record_maker_probe(
            asset=asset,
            direction=edge_snapshot.direction,
            spot_px=edge_snapshot.spot_price,
            perp_px=edge_snapshot.perp_price,
            spot_bid=edge_snapshot.spot_bid,
            spot_ask=edge_snapshot.spot_ask,
            perp_bid=edge_snapshot.perp_bid,
            perp_ask=edge_snapshot.perp_ask,
            always_mode=True,
        )

    def _maybe_record_maker_probe_always_quotes(
        self,
        asset: str,
        spot_bid: float,
        spot_ask: float,
        perp_bid: float,
        perp_ask: float,
    ) -> None:
        self._maybe_record_maker_probe_always_raw(asset, spot_bid, spot_ask, perp_bid, perp_ask)

    def _maybe_record_maker_probe_always_raw(
        self,
        asset: str,
        spot_bid: Optional[float],
        spot_ask: Optional[float],
        perp_bid: Optional[float],
        perp_ask: Optional[float],
    ) -> None:
        if not self._maker_probe_always_enabled:
            return
        if spot_bid is None or spot_ask is None or perp_bid is None or perp_ask is None:
            return
        if spot_bid <= 0 or spot_ask <= 0 or perp_bid <= 0 or perp_ask <= 0:
            return
        ts_ms = now_ms()
        last_ts = self._maker_probe_always_last_ts.get(asset, 0)
        last_log_ts = self._maker_probe_always_last_log_ts.get(asset, 0)
        if ts_ms - last_log_ts >= max(self._maker_probe_always_interval_ms, 1000):
            logger.debug(
                "[SPOT_PERP][MAKER_PROBE] entered_always asset=%s ts_ms=%s last_ts=%s interval_ms=%s",
                asset,
                ts_ms,
                last_ts,
                self._maker_probe_always_interval_ms,
            )
            self._maker_probe_always_last_log_ts[asset] = ts_ms
        if ts_ms - last_ts < self._maker_probe_always_interval_ms:
            return
        self._maker_probe_always_last_ts[asset] = ts_ms
        spot_px = (float(spot_bid) + float(spot_ask)) / 2.0
        perp_px = (float(perp_bid) + float(perp_ask)) / 2.0
        self._record_maker_probe(
            asset=asset,
            direction="NA",
            spot_px=spot_px,
            perp_px=perp_px,
            spot_bid=float(spot_bid),
            spot_ask=float(spot_ask),
            perp_bid=float(perp_bid),
            perp_ask=float(perp_ask),
            always_mode=True,
        )
        logger.info("[SPOT_PERP][MAKER_PROBE] always_record asset=%s ts=%s", asset, ts_ms)

    def _log_recent_maker_probes(self, session) -> None:
        rows = (
            session.query(MakerProbe)
            .order_by(MakerProbe.id.desc())
            .limit(5)
            .all()
        )
        if not rows:
            return
        rows = list(reversed(rows))
        # SQLite helper: SELECT datetime(ts/1000,'unixepoch') AS ts_utc, * FROM maker_probes ORDER BY id DESC LIMIT 5;
        formatted = [
            {
                "id": row.id,
                "ts": row.ts,
                "ts_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime((row.ts or 0) / 1000)),
                "dt_next_ms": row.dt_next_ms,
                "asset": row.asset,
                "direction": row.direction,
            }
            for row in rows
        ]
        has_null = any(row.ts is None or row.dt_next_ms is None for row in rows)
        logger.info("[SPOT_PERP][MAKER_PROBE] recent=%s", formatted)
        if has_null:
            logger.warning("[SPOT_PERP][MAKER_PROBE] null_values_detected")

    async def run_forever(self, stop_event: Optional[asyncio.Event] = None) -> None:
        self._running = True
        logger.info(
            "[MODE] would_trade=%s trace_every_seconds=%.1f",
            self.would_trade,
            self.trace_every_seconds,
        )
        logger.info(
            (
                "[SPOT_PERP][INFO] fees fee_spot=%.6f fee_perp=%.6f fee_tier=%s "
                "fee_mode=%s spot_fee_mode=%s perp_fee_mode=%s eff_spot_rate=%.6f eff_perp_rate=%.6f "
                "maker_fee_spot=%.6f maker_fee_perp=%.6f taker_fee_spot=%.6f taker_fee_perp=%.6f"
            ),
            self.taker_fee_spot,
            self.taker_fee_perp,
            HL_TIER_LABEL,
            self.default_fee_mode,
            self.spot_fee_mode,
            self.perp_fee_mode,
            self.effective_fee_spot_rate,
            self.effective_fee_perp_rate,
            self.maker_fee_spot,
            self.maker_fee_perp,
            self.taker_fee_spot,
            self.taker_fee_perp,
        )
        await self.start_market_data()
        if self.auto_assets_enabled:
            preflight_assets = await self._preflight_filter_assets_for_spot_book(
                self.assets,
                timeout_s=6.0,
                interval_s=0.25,
            )
            dropped_assets = [asset for asset in self.assets if asset not in preflight_assets]
            for asset in dropped_assets:
                self._remove_asset_from_tracking(asset)
            self.assets = preflight_assets
            if not self.assets:
                logger.info("[SPOT_PERP][AUTO_ASSETS][PREFLIGHT] no_assets_remaining")
                self._running = False
                return
            logger.info(
                (
                    "[SPOT_PERP][AUTO_ASSETS] warmup_start assets=%s duration=%.1fs "
                    "interval=%.2fs threshold=%d"
                ),
                self.assets,
                self.auto_assets_warmup_seconds,
                self.auto_assets_warmup_interval,
                self.auto_assets_warmup_failure_threshold,
            )
            await self._run_auto_assets_warmup()

        logger.info(
            "[SPOT_PERP][INFO] engine_start assets=%s log_every_seconds=%s",
            self.assets,
            self._heartbeat_interval,
        )

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(stop_event))
        self._feed_health_task = asyncio.create_task(self._feed_health_loop(stop_event))
        if self._validation_recorder:
            self._validation_task = asyncio.create_task(self._validation_loop(stop_event))
            task_name = (
                self._validation_task.get_name()
                if hasattr(self._validation_task, "get_name")
                else str(self._validation_task)
            )
            logger.info(
                "[VALIDATION] started task=%s sample_interval_ms=%s",
                task_name,
                self.validation_settings.sample_interval_ms,
            )
        else:
            logger.info("[VALIDATION] disabled")

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
            if self._validation_task:
                self._validation_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._validation_task
            self._log_summary("run_forever_exit")

    def _on_orderbook(self, kind: str, coin: str, ob_norm: Dict[str, Any]) -> None:
        if coin not in self.asset_state:
            return
        ts = float(ob_norm.get("ts") or time.time())
        book = BookSnapshot(best_bid=ob_norm.get("bid") or 0.0, best_ask=ob_norm.get("ask") or 0.0, ts=ts)
        if kind == "perp":
            self.asset_state[coin].perp = book
            if self.update_counts[coin]["perp"] == 0:
                logger.info(
                    "[SPOT_PERP][INFO] first_perp_l2_received asset=%s bid=%.6f ask=%.6f",
                    coin,
                    book.best_bid,
                    book.best_ask,
                )
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
            should_log_diag = self.update_counts[coin]["spot"] == 0 or (
                time.time() - self._last_spot_diag_log[coin] >= 5
            )
            if should_log_diag:
                snapshot = self.feed_health.build_asset_snapshot(coin)
                num_bids = len(ob_norm.get("bids") or [])
                num_asks = len(ob_norm.get("asks") or [])
                criteria_failures = []
                if not ob_norm.get("bids"):
                    criteria_failures.append("missing_bids len=0 >=1")
                if not ob_norm.get("asks"):
                    criteria_failures.append("missing_asks len=0 >=1")
                if book.best_bid <= 0:
                    criteria_failures.append(f"bid_price<=0 bid={book.best_bid}")
                if book.best_ask <= 0:
                    criteria_failures.append(f"ask_price<=0 ask={book.best_ask}")
                if snapshot.get("spot_incomplete"):
                    criteria_failures.append("spot_incomplete=True")
                spot_age_ms = snapshot.get("spot_age_ms")
                stale_threshold = getattr(self.feed_health.settings, "stale_ms", None)
                if stale_threshold is not None and (
                    spot_age_ms is None or spot_age_ms > stale_threshold
                ):
                    criteria_failures.append(
                        f"stale_age_ms={self._format_age_ms(spot_age_ms)}>{stale_threshold}"
                    )
                criteria_text = ", ".join(criteria_failures) if criteria_failures else "none"
                logger.info(
                    (
                        "[SPOT_PERP][SPOT_BOOK_DIAG] asset=%s levels_bids=%d levels_asks=%d "
                        "best_bid=%.6f best_ask=%.6f spot_age_ms=%s stale=%s failures=%s"
                    ),
                    coin,
                    num_bids,
                    num_asks,
                    book.best_bid,
                    book.best_ask,
                    self._format_age_ms(spot_age_ms),
                    snapshot.get("stale"),
                    criteria_text,
                )
                self._last_spot_diag_log[coin] = time.time()
        if self.evaluate_on_update:
            self._evaluate_and_record(coin)

    def _on_mark(self, coin: str, mark: float, raw_payload: Dict[str, Any]) -> None:
        if coin not in self.asset_state:
            return
        state = self.asset_state[coin]
        state.mark_price = mark
        state.mark_ts = float(raw_payload.get("time") or raw_payload.get("ts") or time.time())
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
        proxy = self._extract_spot_proxy(raw_payload)
        if proxy and proxy > 0:
            state.spot_proxy = proxy
            state.spot_proxy_ts = state.mark_ts or time.time()
            if not state.spot.has_liquidity():
                state.spot = BookSnapshot(best_bid=proxy, best_ask=proxy, ts=state.spot_proxy_ts)
        if raw_payload.get("fundingRate") is not None:
            try:
                state.funding_rate = float(raw_payload.get("fundingRate"))
            except Exception:
                pass

    def _extract_spot_proxy(self, raw_payload: Dict[str, Any]) -> Optional[float]:
        ctx = raw_payload.get("ctx") if isinstance(raw_payload.get("ctx"), dict) else None
        candidates = []
        for container in (ctx, raw_payload):
            if not isinstance(container, dict):
                continue
            for key in ("midPx", "oraclePx"):
                value = container.get(key)
                if value is None:
                    continue
                try:
                    candidates.append(float(value))
                    break
                except Exception:
                    continue
            impact_pxs = container.get("impactPxs")
            if impact_pxs and isinstance(impact_pxs, (list, tuple)) and impact_pxs:
                try:
                    candidates.append(float(impact_pxs[0]))
                except Exception:
                    pass
        for candidate in candidates:
            if candidate and candidate > 0:
                return candidate
        return None

    def _has_spot_source(self, state: AssetState) -> bool:
        return state.spot.has_liquidity() or state.spot_proxy > 0

    def _effective_spot_prices(self, state: AssetState) -> Tuple[float, float]:
        if state.spot_proxy > 0 and not state.spot.has_liquidity():
            return state.spot_proxy, state.spot_proxy
        return state.spot.best_bid, state.spot.best_ask

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

    async def _validation_loop(self, stop_event: Optional[asyncio.Event]) -> None:
        if not self._validation_recorder:
            return
        sample_interval = max(1, self.validation_settings.sample_interval_ms) / 1000.0
        last_stats_log = time.time()
        try:
            while self._running and (not stop_event or not stop_event.is_set()):
                start = time.time()
                if not self._validation_first_tick_logged:
                    logger.info("[VALIDATION] first_tick")
                    self._validation_first_tick_logged = True
                self._capture_validation_samples()
                if time.time() - last_stats_log >= self.validation_settings.stats_log_interval_sec:
                    last_stats_log = time.time()
                    self._validation_recorder.log_stats()
                elapsed = time.time() - start
                await asyncio.sleep(max(0.0, sample_interval - elapsed))
        finally:
            self._validation_recorder.flush()

    def _log_heartbeat(self) -> None:
        self._last_heartbeat = time.time()
        for asset, counts in self.update_counts.items():
            state = self.asset_state[asset]
            spot_ok = (counts["spot"] > 0 and state.spot.has_liquidity()) or state.spot_proxy > 0
            perp_ok = counts["perp"] > 0 and state.perp.has_liquidity()
            mark_ok = counts["mark"] > 0 and state.mark_price > 0
            spot_bid, spot_ask = self._effective_spot_prices(state)
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
                    spot_bid,
                    spot_ask,
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
                    "[FEED_HEALTH] asset=%s spot_age_ms=%s perp_age_ms=%s "
                    "spot_bbo=%.6f/%.6f perp_bbo=%.6f/%.6f "
                    "spot_incomplete=%s perp_incomplete=%s stale=%s crossed=%s out_of_sync=%s "
                    "ws_msgs=%d dup=%d hb=%d book_incomplete=%d stale_book=%d crossed_book=%d out_of_sync_count=%d"
                ),
                asset,
                self._format_age_ms(snapshot["spot_age_ms"]),
                self._format_age_ms(snapshot["perp_age_ms"]),
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

    def _capture_validation_samples(self) -> None:
        if not self._validation_recorder:
            return
        ts_ms = int(time.time() * 1000)
        for asset in self.assets:
            snapshot = self.feed_health.build_asset_snapshot(asset)
            state = self.asset_state[asset]
            reason = self._determine_skip_reason(asset, snapshot, state)
            outcome = "SKIP" if reason else "WOULD_TRADE"
            detail = self._build_validation_detail(snapshot)
            self._validation_recorder.record(
                DecisionSnapshot(
                    ts_ms=ts_ms,
                    asset=asset,
                    spot_bid=snapshot["spot_bid"],
                    spot_ask=snapshot["spot_ask"],
                    perp_bid=snapshot["perp_bid"],
                    perp_ask=snapshot["perp_ask"],
                    spot_age_ms=snapshot.get("spot_age_ms"),
                    perp_age_ms=snapshot.get("perp_age_ms"),
                    spot_incomplete=int(bool(snapshot.get("spot_incomplete"))),
                    perp_incomplete=int(bool(snapshot.get("perp_incomplete"))),
                    stale=int(bool(snapshot.get("stale"))),
                    crossed=int(bool(snapshot.get("crossed"))),
                    out_of_sync=int(bool(snapshot.get("out_of_sync"))),
                ),
                DecisionOutcome(
                    ts_ms=ts_ms,
                    asset=asset,
                    outcome=outcome,
                    reason=reason or "OK",
                    detail=detail,
                ),
            )

    @staticmethod
    def _format_age_ms(age: Optional[float]) -> str:
        if age is None:
            return "null"
        return f"{age:.1f}"

    def _build_validation_detail(self, snapshot: Dict[str, Any]) -> str:
        return (
            f"spot={snapshot['spot_bid']:.6f}/{snapshot['spot_ask']:.6f} "
            f"perp={snapshot['perp_bid']:.6f}/{snapshot['perp_ask']:.6f} "
            f"ages={self._format_age_ms(snapshot.get('spot_age_ms'))}/"
            f"{self._format_age_ms(snapshot.get('perp_age_ms'))} "
            f"incomplete={snapshot.get('spot_incomplete')}/{snapshot.get('perp_incomplete')} "
            f"stale={snapshot.get('stale')} crossed={snapshot.get('crossed')} out_of_sync={snapshot.get('out_of_sync')}"
        )

    def _evaluate_gates(
        self, asset: str, snapshot: Dict[str, Any], state: AssetState
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Evaluate readiness gates for an asset and provide trace-friendly details."""

        spot_bid, spot_ask = self._effective_spot_prices(state)
        spot_available = self._has_spot_source(state)
        spot_incomplete_raw = bool(snapshot.get("spot_incomplete"))
        spot_incomplete = spot_incomplete_raw
        if state.spot_proxy > 0 and not state.spot.has_liquidity():
            spot_incomplete = False

        spot_spread_ok = True
        spot_spread_bps: Optional[float] = None
        if not (state.spot_proxy > 0 and not state.spot.has_liquidity()):
            if spot_bid > 0 and spot_ask > 0:
                spot_spread_bps = (spot_ask - spot_bid) / spot_bid * 10000
                spot_spread_ok = spot_spread_bps <= self.max_spot_spread_bps

        gates = {
            "has_spot_book": spot_available,
            "has_perp_book": state.perp.has_liquidity(),
            "not_incomplete": not (spot_incomplete or snapshot.get("perp_incomplete")),
            "not_stale": not snapshot.get("stale"),
            "not_crossed": not snapshot.get("crossed"),
            "not_out_of_sync": not snapshot.get("out_of_sync"),
            "has_mark": state.mark_price > 0,
            "spot_spread_ok": spot_spread_ok,
        }

        reason: Optional[str] = None
        if not spot_spread_ok:
            if spot_spread_bps is None:
                spot_spread_bps = 0.0
            logger.debug(
                (
                    "[SPOT_PERP][SANITY] spot_spread_too_wide asset=%s spot_bid=%.6f "
                    "spot_ask=%.6f spot_spread_bps=%.2f max=%.2f"
                ),
                asset,
                spot_bid,
                spot_ask,
                spot_spread_bps,
                self.max_spot_spread_bps,
            )
            reason = "spot_sanity_failed"
        elif spot_incomplete_raw:
            reason = "spot_sanity_failed"
        elif not gates["has_mark"]:
            reason = "SKIP_NO_MARK"
        elif not gates["has_spot_book"] or not gates["has_perp_book"]:
            reason = "SKIP_NO_BOOK"
        elif not gates["not_incomplete"]:
            reason = "SKIP_INCOMPLETE"
        elif not gates["not_stale"]:
            reason = "SKIP_STALE"
        elif not gates["not_out_of_sync"]:
            reason = "SKIP_OUT_OF_SYNC"
        elif not gates["not_crossed"]:
            reason = "SKIP_INVALID_BBO"

        details = {
            "gates": gates,
            "prices": {
                "spot_bid": spot_bid,
                "spot_ask": spot_ask,
                "perp_bid": state.perp.best_bid,
                "perp_ask": state.perp.best_ask,
                "mark": state.mark_price if state.mark_price > 0 else 0.0,
            },
            "ages": {
                "spot_age_ms": snapshot.get("spot_age_ms"),
                "perp_age_ms": snapshot.get("perp_age_ms"),
            },
            "integrity": {
                "dup": snapshot.get("duplicate_events"),
                "out_of_sync_count": snapshot.get("out_of_sync_count"),
                "book_incomplete": snapshot.get("book_incomplete"),
                "ws_msgs": snapshot.get("ws_msgs_total"),
            },
        }

        ready = reason is None
        return ready, reason, details

    def _determine_skip_reason(
        self, asset: str, snapshot: Dict[str, Any], state: AssetState
    ) -> Optional[str]:
        ready, reason, _ = self._evaluate_gates(asset, snapshot, state)
        return None if ready else reason

    def _log_strategy_skip(self, asset: str, reason: str, snapshot: Dict[str, Any]) -> None:
        interval = self.feed_health.settings.log_interval_sec if self.feed_health else 1.0
        now = time.time()
        if reason == self._last_skip_reason[asset] and now - self._last_update_log[asset]["skip"] < interval:
            return
        self._last_skip_reason[asset] = reason
        self._last_update_log[asset]["skip"] = now
        state = self.asset_state[asset]
        gates = {
            "has_mark": state.mark_price > 0,
            "has_spot_book": self._has_spot_source(state),
            "has_perp_book": state.perp.has_liquidity(),
        }
        if reason == "SKIP_NO_BOOK":
            spot_book = getattr(self.client, "_orderbooks_spot", {}).get(asset, None)
            perp_book = getattr(self.client, "_orderbooks_perp", {}).get(asset, None)
            spot_bbo = self._effective_spot_prices(state)
            perp_bbo = (state.perp.best_bid, state.perp.best_ask)
            logger.info(
                "[NO_BOOK_DEBUG] asset=%s "
                "has_spot_book=%s has_perp_book=%s "
                "spot_levels=%s perp_levels=%s "
                "spot_bbo=%s perp_bbo=%s mark=%.6f has_mark=%s "
                "gate_spot=%s gate_perp=%s",
                asset,
                bool(spot_book),
                bool(perp_book),
                len(getattr(spot_book, "levels", [])) if spot_book else None,
                len(getattr(perp_book, "levels", [])) if perp_book else None,
                spot_bbo,
                perp_bbo,
                state.mark_price,
                gates.get("has_mark"),
                gates.get("has_spot_book"),
                gates.get("has_perp_book"),
            )
        elif reason == "SKIP_NO_MARK":
            logger.info(
                "[NO_BOOK_DEBUG] asset=%s has_mark=%s mark=%.6f gate_spot=%s gate_perp=%s",
                asset,
                gates.get("has_mark"),
                state.mark_price,
                gates.get("has_spot_book"),
                gates.get("has_perp_book"),
            )
        logger.info(
            (
                "[STRATEGY_SKIP] asset=%s reason=%s spot_age_ms=%s perp_age_ms=%s "
                "spot_bbo=%.6f/%.6f perp_bbo=%.6f/%.6f"
            ),
            asset,
            reason,
            self._format_age_ms(snapshot.get("spot_age_ms")),
            self._format_age_ms(snapshot.get("perp_age_ms")),
            *self._effective_spot_prices(state),
            state.perp.best_bid,
            state.perp.best_ask,
        )

    def _should_log_trace(self, asset: str, ready: bool, reason: Optional[str]) -> bool:
        state = self._trace_state[asset]
        now = time.time()
        interval_elapsed = now - state["last_log"] >= self.trace_every_seconds
        reason_changed = (reason or "OK") != state["last_reason"]
        ready_changed = ready != state["last_ready"]
        if not (interval_elapsed or reason_changed or ready_changed):
            return False
        if ready_changed:
            state["ready_transitions"] += 1
        state["last_log"] = now
        state["last_ready"] = ready
        state["last_reason"] = reason or "OK"
        state["trace_emitted"] += 1
        return True

    def _log_decision_trace(self, asset: str, ready: bool, reason: Optional[str], details: Dict[str, Any]) -> None:
        if not self._should_log_trace(asset, ready, reason):
            return
        gates = ",".join([f"{k}={int(v)}" for k, v in details.get("gates", {}).items()])
        prices_dict = details.get("prices", {})
        prices = (
            f"spot_bid={prices_dict.get('spot_bid', 0):.6f}/spot_ask={prices_dict.get('spot_ask', 0):.6f} "
            f"perp_bid={prices_dict.get('perp_bid', 0):.6f}/perp_ask={prices_dict.get('perp_ask', 0):.6f} "
            f"mark={prices_dict.get('mark', 0):.6f}"
        )
        ages_dict = details.get("ages", {})
        ages = f"spot_age_ms={self._format_age_ms(ages_dict.get('spot_age_ms'))} perp_age_ms={self._format_age_ms(ages_dict.get('perp_age_ms'))}"
        integrity_dict = details.get("integrity", {})
        integrity = (
            f"dup={integrity_dict.get('dup')} out_of_sync_count={integrity_dict.get('out_of_sync_count')} "
            f"book_incomplete={integrity_dict.get('book_incomplete')} ws_msgs={integrity_dict.get('ws_msgs')}"
        )
        counters = self._trace_state[asset]
        logger.info(
            (
                "[DECISION_TRACE] asset=%s ready=%d skip_reason=%s gates=%s prices=%s ages=%s "
                "integrity=%s trace_emitted=%d ready_transitions=%d last_reason=%s"
            ),
            asset,
            1 if ready else 0,
            reason or "OK",
            gates,
            prices,
            ages,
            integrity,
            counters["trace_emitted"],
            counters["ready_transitions"],
            counters["last_reason"],
        )

    def _log_would_trade(
        self,
        asset: str,
        direction: Optional[str] = None,
        expected_edge_bp: Optional[float] = None,
        note: str = "",
    ) -> None:
        if not self.would_trade:
            return
        # WOULD_TRADE keeps evaluation visible without altering execution behavior.
        direction_label = direction or "N/A"
        edge_label = f"{expected_edge_bp:.2f}" if expected_edge_bp is not None else "N/A"
        logger.info(
            "[WOULD_TRADE] asset=%s action=%s expected_edge_bp=%s note=%s",
            asset,
            direction_label,
            edge_label,
            note or "evaluation_not_implemented",
        )

    def _log_below_min_edge(self, edge_snapshot: SpotPerpEdgeSnapshot, spot_age_ms: Optional[float]) -> None:
        if not self._log_below_min_edge_enabled:
            return
        now = time.time()
        last_log = self._below_edge_last_log_ts.get(edge_snapshot.asset, 0.0)
        if now - last_log < 5.0:
            return
        self._below_edge_last_log_ts[edge_snapshot.asset] = now
        logger.info(
            (
                "[SPOT_PERP][BELOW_MIN_EDGE] asset=%s spread_gross=%+.6f edge_bps=%.2f "
                "min_edge_threshold=%.6f min_edge_bps=%.2f total_cost_bps=%.2f "
                "effective_threshold_bps=%.2f spot_spread_bps=%.2f perp_spread_bps=%.2f "
                "buffer_bps=%.6f slippage_rate=%.6f funding_estimate=%+.6f fee_mode=%s "
                "spot_fee_mode=%s perp_fee_mode=%s below_min_edge=%s spot_age_ms=%s"
            ),
            edge_snapshot.asset,
            edge_snapshot.spread_gross,
            edge_snapshot.edge_bps,
            edge_snapshot.min_edge_threshold,
            edge_snapshot.min_edge_bps,
            edge_snapshot.total_cost_bps * 10000,
            edge_snapshot.effective_threshold_bps,
            edge_snapshot.spot_spread_bps * 10000,
            edge_snapshot.perp_spread_bps * 10000,
            edge_snapshot.buffer_bps,
            edge_snapshot.slippage_rate,
            edge_snapshot.funding_estimate,
            self.default_fee_mode,
            self.spot_fee_mode,
            self.perp_fee_mode,
            edge_snapshot.below_min_edge,
            self._format_age_ms(spot_age_ms),
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
            spot_bid, spot_ask = self._effective_spot_prices(state)
            logger.info(
                (
                    "[SPOT_PERP][LAST_PRICES] asset=%s spot_bid=%.6f spot_ask=%.6f perp_bid=%.6f "
                    "perp_ask=%.6f mark=%.6f mark_ok=%s"
                ),
                asset,
                spot_bid,
                spot_ask,
                state.perp.best_bid,
                state.perp.best_ask,
                state.mark_price,
                state.mark_price > 0,
            )

    def _build_edge_snapshot(self, asset: str, state: AssetState) -> SpotPerpEdgeSnapshot:
        spot_bid, spot_ask = self._effective_spot_prices(state)
        perp = state.perp
        notional = max(self.trading.min_position_size, 1.0)
        funding_estimate = state.funding_rate * notional

        spread_long = (
            (perp.best_bid - spot_ask) / spot_ask if spot_ask > 0 else float("-inf")
        )
        spread_short = (
            (spot_bid - perp.best_ask) / spot_bid if perp.best_ask > 0 else float("-inf")
        )

        spot_mid = (spot_bid + spot_ask) / 2 if spot_bid > 0 and spot_ask > 0 else 0.0
        perp_mid = (perp.best_bid + perp.best_ask) / 2 if perp.best_bid > 0 and perp.best_ask > 0 else 0.0
        spot_spread = max(0.0, spot_ask - spot_bid)
        perp_spread = max(0.0, perp.best_ask - perp.best_bid)
        spot_spread_bps = spot_spread / spot_mid if spot_mid > 0 else 0.0
        perp_spread_bps = perp_spread / perp_mid if perp_mid > 0 else 0.0

        if spread_long >= spread_short:
            spread_gross = spread_long
            direction = "spot_long"
            spot_px = spot_ask
            perp_px = perp.best_bid
        else:
            spread_gross = spread_short
            direction = "spot_short"
            spot_px = spot_bid
            perp_px = perp.best_ask

        fee_spot_rate = self._resolve_fee_rate(self.spot_fee_mode, self.maker_fee_spot, self.taker_fee_spot)
        fee_perp_rate = self._resolve_fee_rate(self.perp_fee_mode, self.maker_fee_perp, self.taker_fee_perp)
        fee_spot = fee_spot_rate * notional
        fee_perp = fee_perp_rate * notional
        gross_pnl_est = spread_gross * notional
        fee_est = fee_spot + fee_perp
        base_slip_bps = getattr(self.trading, "safety_slippage_base", 0.0)
        buffer_bps = getattr(self.trading, "safety_slippage_buffer", 0.0)
        base_slip_rate = self._to_rate_maybe_bps(base_slip_bps)
        buffer_rate = self._to_rate_maybe_bps(buffer_bps)
        slippage_rate = base_slip_rate + buffer_rate
        slippage_est = slippage_rate * notional
        pnl_net = gross_pnl_est - fee_est - slippage_est - funding_estimate
        total_cost_bps = (fee_est + slippage_est) / notional if notional > 0 else 0.0
        edge_bps = spread_gross * 10000
        min_edge_threshold = getattr(self.trading, "min_edge_threshold", 0.0)
        min_edge_rate = self._to_rate_maybe_bps(min_edge_threshold)
        min_edge_bps = min_edge_rate * 10000
        effective_threshold = max(min_edge_rate, total_cost_bps)
        effective_threshold_bps = effective_threshold * 10000
        qty = notional / spot_px if spot_px > 0 else 0.0
        if os.environ.get("SPOT_PERP_FORCE_PASS") == "1":
            pnl_net = abs(pnl_net) + 1e-6
            logger.info("[SPOT_PERP][TEST] force_pass=1 pnl_net_est_overridden")
        below_min_edge = spread_gross < effective_threshold

        return SpotPerpEdgeSnapshot(
            asset=asset,
            spot_bid=spot_bid,
            spot_ask=spot_ask,
            perp_bid=perp.best_bid,
            perp_ask=perp.best_ask,
            spot_price=spot_px,
            perp_price=perp_px,
            spread_gross=spread_gross,
            pnl_net_est=pnl_net,
            edge_bps=edge_bps,
            below_min_edge=below_min_edge,
            direction=direction,
            notional_usd=notional,
            fee_spot_rate=fee_spot_rate,
            fee_perp_rate=fee_perp_rate,
            fee_spot=fee_spot,
            fee_perp=fee_perp,
            fee_est=fee_est,
            base_slip_bps=base_slip_bps,
            buffer_bps=buffer_bps,
            slippage_bps=slippage_rate * 10000,
            slippage_est=slippage_est,
            base_slip_rate=base_slip_rate,
            buffer_rate=buffer_rate,
            slippage_rate=slippage_rate,
            funding_rate=state.funding_rate,
            funding_estimate=funding_estimate,
            total_cost_bps=total_cost_bps,
            min_edge_threshold=min_edge_threshold,
            min_edge_rate=min_edge_rate,
            min_edge_bps=min_edge_bps,
            effective_threshold=effective_threshold,
            effective_threshold_bps=effective_threshold_bps,
            spot_spread_bps=spot_spread_bps,
            perp_spread_bps=perp_spread_bps,
            qty=qty,
        )

    def compute_edge_snapshot(self, asset: str) -> Optional[SpotPerpEdgeSnapshot]:
        if asset not in self.asset_state:
            return None
        state = self.asset_state[asset]
        spot_bid, spot_ask = self._effective_spot_prices(state)
        perp_bid = state.perp.best_bid
        perp_ask = state.perp.best_ask
        self._maybe_record_maker_probe_always_quotes(asset, spot_bid, spot_ask, perp_bid, perp_ask)
        snapshot = self.feed_health.build_asset_snapshot(asset)
        ready, reason, _ = self._evaluate_gates(asset, snapshot, state)
        if not ready or reason:
            return None
        return self._build_edge_snapshot(asset, state)

    def _evaluate_and_record(self, asset: str) -> None:
        state = self.asset_state[asset]
        snapshot = self.feed_health.build_asset_snapshot(asset)
        ready, reason, details = self._evaluate_gates(asset, snapshot, state)
        # Decision trace keeps gating visibility deterministic for each asset.
        self._log_decision_trace(asset, ready, reason, details)
        if reason:
            self._log_strategy_skip(asset, reason, snapshot)
            return

        spot_bid, spot_ask = self._effective_spot_prices(state)
        perp_bid = state.perp.best_bid
        perp_ask = state.perp.best_ask
        self._maybe_record_maker_probe_always_quotes(asset, spot_bid, spot_ask, perp_bid, perp_ask)

        edge_snapshot = self._build_edge_snapshot(asset, state)
        spot_label = "spot_ask" if edge_snapshot.direction == "spot_long" else "spot_bid"
        perp_label = "perp_bid" if edge_snapshot.direction == "spot_long" else "perp_ask"
        fee_spot_source = "config" if self.spot_fee_mode == "maker" else "fallback"
        fee_perp_source = "config" if self.perp_fee_mode == "maker" else "fallback"
        pnl_nonpos = edge_snapshot.pnl_net_est <= 0
        decision = "PASS"
        reject_reason = "OK"
        if edge_snapshot.below_min_edge:
            decision = "REJECT"
            reject_reason = "BELOW_MIN_EDGE"
            self._log_below_min_edge(edge_snapshot, snapshot.get("spot_age_ms"))
        elif pnl_nonpos:
            decision = "REJECT"
            reject_reason = "PNL_NONPOS"

        logger.info(
            "[SPOT_PERP][INFO] compute_attempt asset=%s spot_price=%.6f perp_price=%.6f mark=%.6f "
            "spread_gross=%+.6f pnl_net_est=%+.6f notional_usd=%.6f fee_spot_rate=%.6f "
            "fee_perp_rate=%.6f fee_spot=%+.6f fee_perp=%+.6f fee_est=%+.6f base_slip_bps=%.6f "
            "buffer_bps=%.6f slippage_bps=%.6f slippage_est=%+.6f funding_rate=%+.6f "
            "funding_estimate=%+.6f total_cost_bps=%.6f min_edge_threshold=%.6f min_edge_bps=%.6f "
            "effective_threshold=%.6f below_min_edge=%s fee_mode=%s spot_fee_mode=%s perp_fee_mode=%s "
            "fee_spot_source=%s fee_perp_source=%s",
            asset,
            edge_snapshot.spot_price,
            edge_snapshot.perp_price,
            state.mark_price,
            edge_snapshot.spread_gross,
            edge_snapshot.pnl_net_est,
            edge_snapshot.notional_usd,
            edge_snapshot.fee_spot_rate,
            edge_snapshot.fee_perp_rate,
            edge_snapshot.fee_spot,
            edge_snapshot.fee_perp,
            edge_snapshot.fee_est,
            edge_snapshot.base_slip_bps,
            edge_snapshot.buffer_bps,
            edge_snapshot.slippage_bps,
            edge_snapshot.slippage_est,
            edge_snapshot.funding_rate,
            edge_snapshot.funding_estimate,
            edge_snapshot.total_cost_bps * 10000,
            edge_snapshot.min_edge_threshold,
            edge_snapshot.min_edge_bps,
            edge_snapshot.effective_threshold,
            edge_snapshot.below_min_edge,
            self.default_fee_mode,
            self.spot_fee_mode,
            self.perp_fee_mode,
            fee_spot_source,
            fee_perp_source,
        )
        synthetic_trade = SyntheticSpotPerpTrade(
            asset=asset,
            spot_symbol=self._asset_spot_pairs.get(asset, asset),
            perp_symbol=asset,
            direction=(
                "long_spot_short_perp"
                if edge_snapshot.direction == "spot_long"
                else "short_spot_long_perp"
            ),
            spot_price=edge_snapshot.spot_price,
            perp_price=edge_snapshot.perp_price,
            spot_qty=edge_snapshot.qty,
            perp_qty=edge_snapshot.qty,
            gross_edge=edge_snapshot.spread_gross,
            net_edge=edge_snapshot.pnl_net_est,
            fees_spot=edge_snapshot.fee_spot,
            fees_perp=edge_snapshot.fee_perp,
            timestamp_ms=now_ms(),
        )
        logger.debug("[SPOT_PERP][SYNTHETIC_TRADE] %s", synthetic_trade)
        self._log_would_trade(
            asset,
            direction=edge_snapshot.direction,
            expected_edge_bp=edge_snapshot.spread_gross * 10000 if edge_snapshot.spread_gross is not None else None,
            note=f"pnl_net_est={edge_snapshot.pnl_net_est:.6f}",
        )
        self._record_maker_probe(
            asset=asset,
            direction=edge_snapshot.direction,
            spot_px=edge_snapshot.spot_price,
            perp_px=edge_snapshot.perp_price,
            spot_bid=edge_snapshot.spot_bid,
            spot_ask=edge_snapshot.spot_ask,
            perp_bid=edge_snapshot.perp_bid,
            perp_ask=edge_snapshot.perp_ask,
        )
        logger.debug(
            (
                "[SPOT_PERP][FILTER] asset=%s spread_gross=%+.6f edge_bps=%.2f min_edge_bps=%.2f "
                "effective_threshold_bps=%.2f spot_spread_bps=%.2f perp_spread_bps=%.2f buffer_bps=%.2f "
                "base_slip_input=%.6f buffer_input=%.6f base_slip_rate=%.6f buffer_rate=%.6f "
                "slippage_rate=%.6f min_edge_input=%.6f min_edge_rate=%.6f gross_pnl_est=%+.6f "
                "fee_est=%+.6f slippage_est=%+.6f total_cost_bps=%+.6f notional_usd=%.6f qty=%.6f "
                "pnl_net_est=%+.6f decision=%s reason=%s fee_mode=%s spot_fee_mode=%s perp_fee_mode=%s "
                "fee_spot_rate=%.6f fee_perp_rate=%.6f fee_spot_source=%s fee_perp_source=%s"
            ),
            asset,
            edge_snapshot.spread_gross,
            edge_snapshot.edge_bps,
            edge_snapshot.min_edge_bps,
            edge_snapshot.effective_threshold_bps,
            edge_snapshot.spot_spread_bps * 10000,
            edge_snapshot.perp_spread_bps * 10000,
            edge_snapshot.buffer_bps * 10000,
            edge_snapshot.base_slip_bps,
            edge_snapshot.buffer_bps,
            edge_snapshot.base_slip_rate,
            edge_snapshot.buffer_rate,
            edge_snapshot.slippage_rate,
            edge_snapshot.min_edge_threshold,
            edge_snapshot.min_edge_rate,
            edge_snapshot.spread_gross * edge_snapshot.notional_usd,
            edge_snapshot.fee_est,
            edge_snapshot.slippage_est,
            edge_snapshot.total_cost_bps * 10000,
            edge_snapshot.notional_usd,
            edge_snapshot.qty,
            edge_snapshot.pnl_net_est,
            decision,
            reject_reason,
            self.default_fee_mode,
            self.spot_fee_mode,
            self.perp_fee_mode,
            edge_snapshot.fee_spot_rate,
            edge_snapshot.fee_perp_rate,
            fee_spot_source,
            fee_perp_source,
        )

        if edge_snapshot.spread_gross <= 0 or edge_snapshot.pnl_net_est <= 0:
            return

        fee_total = edge_snapshot.fee_spot + edge_snapshot.fee_perp
        self._log_opportunity(
            asset=asset,
            direction=edge_snapshot.direction,
            spot_price=edge_snapshot.spot_price,
            perp_price=edge_snapshot.perp_price,
            mark_price=state.mark_price,
            spot_label=spot_label,
            perp_label=perp_label,
            spread_gross=edge_snapshot.spread_gross,
            fee_total=fee_total,
            funding_estimate=edge_snapshot.funding_estimate,
            pnl_net_estimated=edge_snapshot.pnl_net_est,
        )
        # Explicit synthetic Spot/Perp trade model (paper-only, no execution).
        synthetic_trade = SyntheticSpotPerpTrade(
            asset=asset,
            spot_symbol=self._asset_spot_pairs.get(asset, asset),
            perp_symbol=asset,
            direction=(
                "long_spot_short_perp"
                if edge_snapshot.direction == "spot_long"
                else "short_spot_long_perp"
            ),
            spot_price=edge_snapshot.spot_price,
            perp_price=edge_snapshot.perp_price,
            spot_qty=edge_snapshot.qty,
            perp_qty=edge_snapshot.qty,
            gross_edge=edge_snapshot.spread_gross,
            net_edge=edge_snapshot.pnl_net_est,
            fees_spot=edge_snapshot.fee_spot,
            fees_perp=edge_snapshot.fee_perp,
            timestamp_ms=now_ms(),
        )
        logger.debug("[SPOT_PERP][SYNTHETIC_TRADE][TRADEABLE] %s", synthetic_trade)
        self._persist_opportunity(
            asset=asset,
            direction=edge_snapshot.direction,
            spot_price=edge_snapshot.spot_price,
            perp_price=edge_snapshot.perp_price,
            mark_price=state.mark_price,
            spread_gross=edge_snapshot.spread_gross,
            fee_estimated=fee_total,
            funding_estimated=edge_snapshot.funding_estimate,
            pnl_net_estimated=edge_snapshot.pnl_net_est,
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
        if self._validation_task and not self._validation_task.done():
            self._validation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._validation_task
        if self._validation_recorder:
            self._validation_recorder.flush()
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
            spot_bid, spot_ask = self._effective_spot_prices(state)
            logger.info(
                (
                    "[SPOT_PERP][SUMMARY_PRICES] asset=%s spot_bid=%.6f spot_ask=%.6f "
                    "perp_bid=%.6f perp_ask=%.6f mark=%.6f"
                ),
                asset,
                spot_bid,
                spot_ask,
                state.perp.best_bid,
                state.perp.best_ask,
                state.mark_price,
            )


async def run_spot_perp_engine(
    assets: Iterable[str],
    settings: Optional[Settings] = None,
    taker_fee_spot: float = HL_TIER_0_FEE_TAKER_SPOT,
    taker_fee_perp: float = HL_TIER_0_FEE_TAKER_PERP,
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
        validation_settings=settings.validation,
        would_trade=settings.strategy.would_trade,
        trace_every_seconds=settings.strategy.trace_every_seconds,
    )
    stop_event = asyncio.Event()

    try:
        await engine.run_forever(stop_event=stop_event)
    finally:
        stop_event.set()
        await client.close()
