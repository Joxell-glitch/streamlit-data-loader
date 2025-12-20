import time

from src.observability.feed_health import FeedHealthTracker


def test_feed_health_accepts_valid_bbo_without_levels():
    tracker = FeedHealthTracker()

    tracker.on_book_update(
        "BTC", "spot", best_bid=100.0, best_ask=101.0, ts=time.time(), bids=[], asks=[]
    )

    snapshot = tracker.build_asset_snapshot("BTC")

    assert snapshot["spot_incomplete"] is False
    assert snapshot["crossed"] is False
    assert snapshot["spot_bid"] == 100.0
    assert snapshot["spot_ask"] == 101.0


def test_feed_health_marks_crossed_bbo_incomplete():
    tracker = FeedHealthTracker()

    tracker.on_book_update(
        "BTC", "spot", best_bid=101.0, best_ask=100.0, ts=time.time(), bids=[], asks=[]
    )

    snapshot = tracker.build_asset_snapshot("BTC")

    assert snapshot["spot_incomplete"] is True
    assert snapshot["crossed"] is True


def test_feed_health_out_of_sync_detection_uses_seconds():
    tracker = FeedHealthTracker(settings=None)
    tracker.settings.out_of_sync_ms = 500

    tracker.on_book_update(
        "ETH", "spot", best_bid=100.0, best_ask=101.0, ts=1700000000000.0, bids=[], asks=[]
    )
    tracker.on_book_update(
        "ETH", "perp", best_bid=100.0, best_ask=101.0, ts=1700000000.2, bids=[], asks=[]
    )

    snapshot = tracker.build_asset_snapshot("ETH")
    assert snapshot["out_of_sync"] is False

    tracker.on_book_update(
        "ETH", "perp", best_bid=100.0, best_ask=101.0, ts=1700000001.0, bids=[], asks=[]
    )

    snapshot = tracker.build_asset_snapshot("ETH")
    assert snapshot["out_of_sync"] is True
