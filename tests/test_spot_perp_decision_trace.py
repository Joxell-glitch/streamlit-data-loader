from src.config.models import FeedHealthSettings, TradingSettings
from src.observability.feed_health import FeedHealthTracker
from src.strategy.spot_perp_paper import AssetState, BookSnapshot, SpotPerpPaperEngine


class DummyClient:
    def set_feed_health_tracker(self, tracker):
        self.tracker = tracker

    def add_orderbook_listener(self, _):
        return None

    def add_mark_listener(self, _):
        return None


trading_settings = TradingSettings(
    quote_asset="USDC",
    initial_quote_balance=1000.0,
    min_position_size=1.0,
    max_position_size=10.0,
    min_edge_threshold=0.0,
    safety_slippage_buffer=0.0,
    max_concurrent_triangles=1,
)


def _build_engine():
    client = DummyClient()
    feed_health_settings = FeedHealthSettings()
    feed_health = FeedHealthTracker(feed_health_settings)
    engine = SpotPerpPaperEngine(
        client,
        assets=["BTC"],
        trading=trading_settings,
        feed_health_settings=feed_health_settings,
        feed_health_tracker=feed_health,
    )
    return engine


def test_evaluate_gates_marks_missing_returns_skip():
    engine = _build_engine()
    state = AssetState(
        spot=BookSnapshot(best_bid=10, best_ask=11),
        perp=BookSnapshot(best_bid=9, best_ask=10),
        mark_price=0.0,
    )
    snapshot = {
        "spot_incomplete": False,
        "perp_incomplete": False,
        "stale": False,
        "crossed": False,
        "out_of_sync": False,
        "spot_age_ms": 1.0,
        "perp_age_ms": 1.0,
    }
    ready, reason, details = engine._evaluate_gates("BTC", snapshot, state)
    assert ready is False
    assert reason == "SKIP_NO_MARK"
    assert details["gates"]["has_mark"] is False


def test_evaluate_gates_incomplete_books_returns_skip_incomplete():
    engine = _build_engine()
    state = AssetState(
        spot=BookSnapshot(best_bid=10, best_ask=11),
        perp=BookSnapshot(best_bid=9, best_ask=10),
        mark_price=100.0,
    )
    snapshot = {
        "spot_incomplete": True,
        "perp_incomplete": False,
        "stale": False,
        "crossed": False,
        "out_of_sync": False,
        "spot_age_ms": 1.0,
        "perp_age_ms": 1.0,
    }
    ready, reason, details = engine._evaluate_gates("BTC", snapshot, state)
    assert ready is False
    assert reason == "spot_sanity_failed"
    assert details["gates"]["not_incomplete"] is False


def test_evaluate_gates_all_good_ready():
    engine = _build_engine()
    state = AssetState(
        spot=BookSnapshot(best_bid=10, best_ask=11),
        perp=BookSnapshot(best_bid=9, best_ask=10),
        mark_price=100.0,
    )
    snapshot = {
        "spot_incomplete": False,
        "perp_incomplete": False,
        "stale": False,
        "crossed": False,
        "out_of_sync": False,
        "spot_age_ms": 1.0,
        "perp_age_ms": 1.0,
    }
    ready, reason, _ = engine._evaluate_gates("BTC", snapshot, state)
    assert ready is True
    assert reason is None
