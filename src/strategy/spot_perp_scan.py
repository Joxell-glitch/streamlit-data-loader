from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from src.strategy.spot_perp_paper import SpotPerpDecision


@dataclass
class AssetScanMetrics:
    asset: str
    observations: int = 0
    accept_count: int = 0
    max_edge_bps: Optional[float] = None
    max_effective_threshold_bps: Optional[float] = None
    max_edge_minus_threshold_bps: Optional[float] = None
    max_pnl_net_est: Optional[float] = None
    best_fee_mode: str = "n/a"
    _best_edge_minus_pnl_net_est: Optional[float] = field(default=None, repr=False)


def update_scan_metrics(
    metrics_by_asset: Dict[str, AssetScanMetrics],
    observation: SpotPerpDecision,
) -> None:
    metrics = metrics_by_asset.setdefault(observation.asset, AssetScanMetrics(asset=observation.asset))
    metrics.observations += 1
    if observation.decision == "PASS":
        metrics.accept_count += 1

    edge_minus_threshold = observation.edge_bps - observation.effective_threshold_bps
    metrics.max_edge_bps = _max_or_none(metrics.max_edge_bps, observation.edge_bps)
    metrics.max_effective_threshold_bps = _max_or_none(
        metrics.max_effective_threshold_bps, observation.effective_threshold_bps
    )
    metrics.max_edge_minus_threshold_bps = _max_or_none(
        metrics.max_edge_minus_threshold_bps, edge_minus_threshold
    )
    metrics.max_pnl_net_est = _max_or_none(metrics.max_pnl_net_est, observation.pnl_net_est)

    best_edge = metrics.max_edge_minus_threshold_bps
    best_pnl_for_edge = metrics._best_edge_minus_pnl_net_est
    is_better_edge = best_edge is None or edge_minus_threshold > best_edge
    is_tied_edge_better_pnl = edge_minus_threshold == best_edge and (
        best_pnl_for_edge is None or observation.pnl_net_est > best_pnl_for_edge
    )
    if is_better_edge or is_tied_edge_better_pnl:
        metrics._best_edge_minus_pnl_net_est = observation.pnl_net_est
        metrics.best_fee_mode = observation.fee_mode


def _max_or_none(current: Optional[float], candidate: float) -> float:
    if current is None:
        return candidate
    return max(current, candidate)
