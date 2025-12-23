from src.strategy.spot_perp_paper import SpotPerpDecision
from src.strategy.spot_perp_scan import update_scan_metrics


def test_update_scan_metrics_tracks_best_fee_mode():
    metrics = {}

    update_scan_metrics(
        metrics,
        SpotPerpDecision(
            asset="ETH",
            edge_bps=10.0,
            effective_threshold_bps=5.0,
            pnl_net_est=1.5,
            decision="PASS",
            reason="OK",
            fee_mode="maker",
            spot_fee_mode="maker",
            perp_fee_mode="maker",
            fee_spot_rate=0.0,
            fee_perp_rate=0.0,
        ),
    )
    update_scan_metrics(
        metrics,
        SpotPerpDecision(
            asset="ETH",
            edge_bps=12.0,
            effective_threshold_bps=4.0,
            pnl_net_est=1.0,
            decision="PASS",
            reason="OK",
            fee_mode="taker",
            spot_fee_mode="taker",
            perp_fee_mode="taker",
            fee_spot_rate=0.001,
            fee_perp_rate=0.0005,
        ),
    )

    metric = metrics["ETH"]
    assert metric.observations == 2
    assert metric.accept_count == 2
    assert metric.max_edge_bps == 12.0
    assert metric.max_effective_threshold_bps == 5.0
    assert metric.max_edge_minus_threshold_bps == 8.0
    assert metric.max_pnl_net_est == 1.5
    assert metric.best_fee_mode == "taker"


def test_update_scan_metrics_tracks_rejects():
    metrics = {}

    update_scan_metrics(
        metrics,
        SpotPerpDecision(
            asset="SOL",
            edge_bps=1.0,
            effective_threshold_bps=2.0,
            pnl_net_est=-0.1,
            decision="REJECT",
            reason="PNL_NONPOS",
            fee_mode="maker",
            spot_fee_mode="maker",
            perp_fee_mode="maker",
            fee_spot_rate=0.0,
            fee_perp_rate=0.0,
        ),
    )

    metric = metrics["SOL"]
    assert metric.observations == 1
    assert metric.accept_count == 0
