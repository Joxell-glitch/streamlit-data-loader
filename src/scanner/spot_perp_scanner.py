from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Tuple

from src.cli.spot_perp_assets import select_auto_assets
from src.config.models import SpotPerpScannerSettings
from src.core.logging import get_logger
from src.hyperliquid_client.client import HyperliquidClient
from src.strategy.spot_perp_paper import SpotPerpEdgeSnapshot, SpotPerpPaperEngine

logger = get_logger(__name__)


@dataclass
class EdgeSample:
    ts: float
    edge_bps: float
    pnl_net_est: float
    below_min_edge: bool


@dataclass
class AssetMetrics:
    count_hits: int
    avg_edge_bps: float
    p50_edge_bps: float
    p90_edge_bps: float
    avg_pnl_net_est: float
    last_seen_ts: float
    instability_penalty: float = 0.0
    score: float = 0.0


@dataclass
class ShortlistSnapshot:
    timestamp: str
    window_minutes: int
    top_assets: List[str]
    per_asset_metrics: Dict[str, AssetMetrics] = field(default_factory=dict)


class SpotPerpScanner:
    def __init__(
        self,
        client: HyperliquidClient,
        engine: SpotPerpPaperEngine,
        settings: SpotPerpScannerSettings,
        assets: Iterable[str],
        *,
        auto_assets_enabled: bool = False,
        auto_assets_n: int = 15,
        output_path: str = "data/spot_perp_shortlist.json",
    ) -> None:
        self.client = client
        self.engine = engine
        self.settings = settings
        self.assets: List[str] = [asset.upper() for asset in assets]
        self.auto_assets_enabled = auto_assets_enabled
        self.auto_assets_n = auto_assets_n
        self.output_path = Path(output_path)
        self._samples: Dict[str, Deque[EdgeSample]] = {
            asset: deque() for asset in self.assets
        }
        self._last_seen: Dict[str, float] = {asset: 0.0 for asset in self.assets}
        self._shortlist: List[str] = []
        self._confirm_counts: Dict[str, int] = {}
        self._removal_deadlines: Dict[str, float] = {}
        self._last_universe_refresh = 0.0
        self._last_ranked_assets: List[str] = []

    async def start(self) -> None:
        if self.assets:
            self.engine.add_assets(self.assets)
        await self.engine.start_market_data()
        self._last_universe_refresh = time.time()

    async def refresh_universe(self) -> None:
        if not self.auto_assets_enabled:
            return
        selected = await select_auto_assets(self.client, limit=self.auto_assets_n)
        selected = [asset.upper() for asset in selected]
        if not selected:
            logger.warning("[SPOT_PERP][SCANNER] auto_assets_refresh empty_selection")
            return
        new_assets = [asset for asset in selected if asset not in self.assets]
        removed_assets = [asset for asset in self.assets if asset not in selected]
        self.assets = selected
        for asset in new_assets:
            self._samples.setdefault(asset, deque())
            self._last_seen.setdefault(asset, 0.0)
        for asset in removed_assets:
            self._samples.pop(asset, None)
            self._last_seen.pop(asset, None)
            if asset in self._shortlist:
                self._shortlist.remove(asset)
            self._confirm_counts.pop(asset, None)
            self._removal_deadlines.pop(asset, None)
        if new_assets:
            self.engine.add_assets(new_assets)
            await self.engine.start_market_data()
        logger.info(
            "[SPOT_PERP][SCANNER] auto_assets_refresh added=%s removed=%s total=%d",
            ",".join(new_assets) or "none",
            ",".join(removed_assets) or "none",
            len(self.assets),
        )
        self._last_universe_refresh = time.time()

    @staticmethod
    def _percentile(values: List[float], percentile: float) -> float:
        if not values:
            return 0.0
        if percentile <= 0:
            return min(values)
        if percentile >= 1:
            return max(values)
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * percentile
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        d0 = sorted_vals[int(f)] * (c - k)
        d1 = sorted_vals[int(c)] * (k - f)
        return d0 + d1

    def _record_sample(self, asset: str, snapshot: SpotPerpEdgeSnapshot, now: float) -> None:
        self._samples.setdefault(asset, deque()).append(
            EdgeSample(
                ts=now,
                edge_bps=snapshot.edge_bps,
                pnl_net_est=snapshot.pnl_net_est,
                below_min_edge=snapshot.below_min_edge,
            )
        )
        self._last_seen[asset] = now

    def _prune_samples(self, asset: str, now: float) -> None:
        window_seconds = self.settings.window_minutes * 60
        samples = self._samples.get(asset)
        if not samples:
            return
        cutoff = now - window_seconds
        while samples and samples[0].ts < cutoff:
            samples.popleft()

    def _compute_metrics(self, now: float) -> Dict[str, AssetMetrics]:
        metrics: Dict[str, AssetMetrics] = {}
        for asset, samples in self._samples.items():
            if not samples:
                metrics[asset] = AssetMetrics(
                    count_hits=0,
                    avg_edge_bps=0.0,
                    p50_edge_bps=0.0,
                    p90_edge_bps=0.0,
                    avg_pnl_net_est=0.0,
                    last_seen_ts=self._last_seen.get(asset, 0.0),
                )
                continue
            self._prune_samples(asset, now)
            hit_edges = [sample.edge_bps for sample in samples if not sample.below_min_edge]
            hit_pnl = [sample.pnl_net_est for sample in samples if not sample.below_min_edge]
            count_hits = len(hit_edges)
            avg_edge = sum(hit_edges) / count_hits if count_hits else 0.0
            avg_pnl = sum(hit_pnl) / count_hits if count_hits else 0.0
            p50 = self._percentile(hit_edges, 0.5) if hit_edges else 0.0
            p90 = self._percentile(hit_edges, 0.9) if hit_edges else 0.0
            metrics[asset] = AssetMetrics(
                count_hits=count_hits,
                avg_edge_bps=avg_edge,
                p50_edge_bps=p50,
                p90_edge_bps=p90,
                avg_pnl_net_est=avg_pnl,
                last_seen_ts=self._last_seen.get(asset, 0.0),
            )
        return metrics

    def _compute_score(self, metrics: AssetMetrics) -> Tuple[float, float]:
        weights = self.settings.weights or {}
        count_hits_weight = weights.get("count_hits", 1.0)
        avg_edge_weight = weights.get("avg_edge_bps", 1.0)
        p90_edge_weight = weights.get("p90_edge_bps", 1.0)
        instability_weight = weights.get("instability_penalty", 1.0)
        if metrics.count_hits <= 1:
            instability_penalty = metrics.p90_edge_bps
        else:
            instability_penalty = max(0.0, metrics.p90_edge_bps - metrics.p50_edge_bps)
        score = (
            count_hits_weight * metrics.count_hits
            + avg_edge_weight * metrics.avg_edge_bps
            + p90_edge_weight * metrics.p90_edge_bps
            - instability_weight * instability_penalty
        )
        return score, instability_penalty

    def _rank_assets(self, metrics: Dict[str, AssetMetrics]) -> List[str]:
        ranked: List[Tuple[str, AssetMetrics]] = []
        for asset, item in metrics.items():
            score, penalty = self._compute_score(item)
            item.score = score
            item.instability_penalty = penalty
            ranked.append((asset, item))
        ranked.sort(key=lambda entry: entry[1].score, reverse=True)
        return [asset for asset, _ in ranked]

    def _update_shortlist(self, ranked_assets: List[str], now: float) -> List[str]:
        desired = ranked_assets[: self.settings.top_n]
        desired_set = set(desired)
        for asset in desired_set:
            self._confirm_counts[asset] = self._confirm_counts.get(asset, 0) + 1
        for asset in list(self._confirm_counts):
            if asset not in desired_set:
                self._confirm_counts[asset] = 0

        for asset in list(self._shortlist):
            if asset in desired_set:
                self._removal_deadlines.pop(asset, None)
                continue
            if asset not in self._removal_deadlines:
                cooldown = self.settings.removal_cooldown_minutes * 60
                self._removal_deadlines[asset] = now + cooldown
            elif now >= self._removal_deadlines[asset]:
                self._shortlist.remove(asset)
                self._removal_deadlines.pop(asset, None)

        if len(self._shortlist) < self.settings.top_n:
            for asset in desired:
                if asset in self._shortlist:
                    continue
                if self._confirm_counts.get(asset, 0) < self.settings.min_cycles_confirm:
                    continue
                self._shortlist.append(asset)
                if len(self._shortlist) >= self.settings.top_n:
                    break

        ordered = [asset for asset in ranked_assets if asset in self._shortlist]
        self._shortlist = ordered
        return list(self._shortlist)

    def _format_top_assets(self, ranked_assets: List[str], metrics: Dict[str, AssetMetrics], limit: int) -> str:
        entries = []
        for asset in ranked_assets[:limit]:
            item = metrics.get(asset)
            if not item:
                continue
            entries.append(
                f"{asset}(score={item.score:.2f} hits={item.count_hits} p90={item.p90_edge_bps:.2f})"
            )
        return ", ".join(entries)

    def _persist_snapshot(self, snapshot: ShortlistSnapshot) -> None:
        payload = {
            "timestamp": snapshot.timestamp,
            "window_minutes": snapshot.window_minutes,
            "top_assets": snapshot.top_assets,
            "per_asset_metrics": {
                asset: asdict(metrics) for asset, metrics in snapshot.per_asset_metrics.items()
            },
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

    async def run_cycle(self) -> ShortlistSnapshot:
        now = time.time()
        for asset in list(self.assets):
            snapshot = self.engine.compute_edge_snapshot(asset)
            if snapshot:
                self._record_sample(asset, snapshot, now)
        metrics = self._compute_metrics(now)
        ranked_assets = self._rank_assets(metrics)
        self._last_ranked_assets = ranked_assets
        shortlist = self._update_shortlist(ranked_assets, now)
        timestamp = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        snapshot = ShortlistSnapshot(
            timestamp=timestamp,
            window_minutes=self.settings.window_minutes,
            top_assets=shortlist,
            per_asset_metrics=metrics,
        )
        self._persist_snapshot(snapshot)
        logger.info(
            "[SPOT_PERP][SCANNER] cycle_summary top10=%s",
            self._format_top_assets(ranked_assets, metrics, limit=10),
        )
        return snapshot

    async def run(
        self,
        *,
        once: bool = False,
        duration_seconds: Optional[int] = None,
    ) -> None:
        await self.start()
        await asyncio.sleep(1.0)
        start_time = time.time()
        while True:
            now = time.time()
            if self.auto_assets_enabled:
                refresh_interval = self.settings.refresh_universe_minutes * 60
                if now - self._last_universe_refresh >= refresh_interval:
                    await self.refresh_universe()
            snapshot = await self.run_cycle()
            if once:
                top15 = self._format_top_assets(
                    self._last_ranked_assets,
                    snapshot.per_asset_metrics,
                    limit=15,
                )
                logger.info("[SPOT_PERP][SCANNER] once_top15=%s", top15)
                return
            if duration_seconds is not None and now - start_time >= duration_seconds:
                logger.info("[SPOT_PERP][SCANNER] duration_reached seconds=%s", duration_seconds)
                return
            await asyncio.sleep(max(0.1, self.settings.interval_seconds))
