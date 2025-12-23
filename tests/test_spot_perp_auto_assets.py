import pytest

from src.cli.spot_perp_assets import select_auto_assets_from_meta


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
