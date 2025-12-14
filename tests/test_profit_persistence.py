from datetime import datetime, timezone

from src.arb.profit_persistence import ProfitRecorder, load_recent_profitable, load_top_per_hour
from src.arb.triangular_scanner import Opportunity


def _make_opportunity(ts: float, triangle_id: int, final_amount: float) -> Opportunity:
    return Opportunity(
        triangle_id=triangle_id,
        assets=("A", "B", "C"),
        timestamp=ts,
        initial_size=100.0,
        theoretical_final_amount=final_amount,
        theoretical_edge=(final_amount / 100.0) - 1,
        slippage=(0.0, 0.0, 0.0),
    )


def test_persist_and_load(tmp_path):
    recorder = ProfitRecorder(data_dir=str(tmp_path), top_n_per_hour=2)
    ts = datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc).timestamp()
    recorder.record_opportunity(_make_opportunity(ts, 1, 110.0))
    recorder.record_opportunity(_make_opportunity(ts + 10, 2, 120.0))

    profitable = load_recent_profitable(5, data_dir=str(tmp_path))
    assert len(profitable) == 2
    assert profitable[0]["triangle"]["id"] == 2  # Last appended first

    top_hours = load_top_per_hour(200000, data_dir=str(tmp_path))
    assert len(top_hours) == 1
    records = top_hours[0]["records"]
    assert len(records) == 2
    assert records[0]["triangle"]["id"] == 2
    assert records[0]["profit_absolute"] > records[1]["profit_absolute"]
