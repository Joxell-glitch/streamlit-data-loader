import pytest

from src.cli.spot_perp_assets import select_auto_assets_from_meta
from src.config.models import FeedHealthSettings, TradingSettings
from src.observability.feed_health import FeedHealthTracker
from src.strategy.spot_perp_paper import BookSnapshot, SpotPerpPaperEngine


class DummyClient:
    def set_feed_health_tracker(self, tracker):
        self.tracker = tracker

    def add_orderbook_listener(self, _):
        return None

    def add_mark_listener(self, _):
        return None


def test_select_auto_assets_prefers_high_spread_then_low_volume():
    spot_meta = {
        "universe": [
            {"tokens": [1, 2]},
            {"tokens": [3, 2]},
            {"tokens": [4, 2]},
        ],
        "tokens": [
            {"index": 1, "name": "AAA"},
            {"index": 3, "name": "BBB"},
            {"index": 4, "name": "CCC"},
            {"index": 2, "name": "USD"},
        ],
        "assetCtxs": [
            {"coin": "AAA", "bidPx": "99", "askPx": "101", "dayNtlVlm": "500"},
            {"coin": "BBB", "bidPx": "98", "askPx": "102", "dayNtlVlm": "100"},
            {"coin": "CCC", "bidPx": "99.5", "askPx": "100.5", "dayNtlVlm": "50"},
        ],
    }
    perp_meta = {"universe": [{"name": "AAA"}, {"name": "BBB"}, {"name": "CCC"}]}

    selected, reason = select_auto_assets_from_meta(spot_meta, perp_meta, limit=2, major_asset="ETH")

    assert selected == ["BBB", "AAA"]
    assert reason == "spread_desc_volume_asc"


def test_select_auto_assets_filters_to_spot_and_perp_and_adds_major():
    spot_meta = {
        "universe": [{"name": "AAA"}, {"name": "ETH"}, {"name": "SPOTONLY"}],
        "assetCtxs": [
            {"coin": "AAA", "dayNtlVlm": "500"},
            {"coin": "ETH", "dayNtlVlm": "2000"},
            {"coin": "SPOTONLY", "dayNtlVlm": "10"},
        ],
    }
    perp_meta = {"universe": [{"name": "AAA"}, {"name": "ETH"}, {"name": "PERPONLY"}]}

    selected, reason = select_auto_assets_from_meta(spot_meta, perp_meta, limit=1, major_asset="ETH")

    assert selected == ["ETH"]
    assert "major=ETH" in reason


def test_select_auto_assets_falls_back_to_volume_when_spread_missing():
    spot_meta = {
        "universe": [{"name": "AAA"}, {"name": "BBB"}],
        "assetCtxs": [
            {"coin": "AAA", "dayNtlVlm": "1000"},
            {"coin": "BBB", "dayNtlVlm": "10"},
        ],
    }
    perp_meta = {"universe": [{"name": "AAA"}, {"name": "BBB"}]}

    selected, reason = select_auto_assets_from_meta(spot_meta, perp_meta, limit=1, major_asset="ETH")

    assert selected == ["BBB"]
    assert reason == "volume_asc"


def test_auto_assets_warmup_drops_spread_failures():
    trading_settings = TradingSettings(
        quote_asset="USDC",
        initial_quote_balance=1000.0,
        min_position_size=1.0,
        max_position_size=10.0,
        min_edge_threshold=0.0,
        safety_slippage_buffer=0.0,
        max_concurrent_triangles=1,
        max_spot_spread_bps=50.0,
    )
    feed_health_settings = FeedHealthSettings()
    feed_health = FeedHealthTracker(feed_health_settings)
    engine = SpotPerpPaperEngine(
        DummyClient(),
        assets=["BERA"],
        trading=trading_settings,
        feed_health_settings=feed_health_settings,
        feed_health_tracker=feed_health,
        auto_assets_enabled=True,
        auto_assets_warmup_seconds=0.3,
        auto_assets_warmup_interval=0.02,
        auto_assets_warmup_failure_threshold=3,
    )
    engine.asset_state["BERA"].spot = BookSnapshot(best_bid=1.0, best_ask=1.5)

    def _snapshot(_asset):
        return {
            "spot_incomplete": False,
            "perp_incomplete": False,
            "stale": False,
            "crossed": False,
            "out_of_sync": False,
            "spot_age_ms": 1.0,
            "perp_age_ms": 1.0,
        }

    engine.feed_health.build_asset_snapshot = _snapshot

    import asyncio

    asyncio.run(engine._run_auto_assets_warmup())

    assert "BERA" not in engine.assets
    assert "BERA" not in engine.asset_state

    called = {"compute": False}

    def _called(_asset):
        called["compute"] = True

    engine._evaluate_and_record = _called
    engine._on_orderbook(
        "spot",
        "BERA",
        {"bid": 1.0, "ask": 1.5, "ts": 1.0, "bids": [[1.0, 1.0]], "asks": [[1.5, 1.0]]},
    )
    assert called["compute"] is False
