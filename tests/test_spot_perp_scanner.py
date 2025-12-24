from collections import deque

from src.config.models import SpotPerpScannerSettings
from src.scanner.spot_perp_scanner import EdgeSample, SpotPerpScanner


class DummyClient:
    pass


class DummyEngine:
    def add_assets(self, _):
        return []

    async def start_market_data(self):
        return None


def test_percentile_interpolation():
    scanner = SpotPerpScanner(
        client=DummyClient(),
        engine=DummyEngine(),
        settings=SpotPerpScannerSettings(),
        assets=["BTC"],
    )
    assert scanner._percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5


def test_metrics_rollup_hits_only():
    scanner = SpotPerpScanner(
        client=DummyClient(),
        engine=DummyEngine(),
        settings=SpotPerpScannerSettings(window_minutes=30),
        assets=["BTC"],
    )
    now = 100.0
    scanner._samples["BTC"] = deque(
        [
            EdgeSample(ts=now - 10, edge_bps=5.0, pnl_net_est=1.0, below_min_edge=False),
            EdgeSample(ts=now - 5, edge_bps=10.0, pnl_net_est=2.0, below_min_edge=False),
            EdgeSample(ts=now - 1, edge_bps=-2.0, pnl_net_est=-1.0, below_min_edge=True),
        ]
    )
    metrics = scanner._compute_metrics(now)
    btc = metrics["BTC"]
    assert btc.count_hits == 2
    assert btc.avg_edge_bps == 7.5
    assert btc.p50_edge_bps == 7.5
    assert btc.p90_edge_bps == 9.5
    assert btc.avg_pnl_net_est == 1.5
