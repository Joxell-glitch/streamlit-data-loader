from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.arb.profit_persistence import ProfitRecorder, load_recent_profitable, load_top_per_hour
from src.arb.triangular_scanner import Opportunity
from src.db.models import Base


def _session_factory(tmp_path):
    db_path = tmp_path / "db.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def scope():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    return scope, str(db_path)


def _make_opportunity(ts: float, triangle_id: int, final_amount: float) -> Opportunity:
    edge = (final_amount / 100.0) - 1
    return Opportunity(
        triangle_id=triangle_id,
        assets=("A", "B", "C"),
        timestamp=ts,
        initial_size=100.0,
        theoretical_final_amount=final_amount,
        theoretical_edge=edge,
        slippage=(0.0, 0.0, 0.0),
        prices=(1.0, 1.0, 1.0),
        profit_absolute=final_amount - 100.0,
        profit_percent=edge * 100,
    )


def test_persist_and_load(tmp_path):
    session_factory, db_path = _session_factory(tmp_path)
    recorder = ProfitRecorder(db_session_factory=session_factory, db_path=db_path)
    ts = datetime.now(timezone.utc).timestamp()
    recorder.record_opportunity(_make_opportunity(ts, 1, 110.0))
    recorder.record_opportunity(_make_opportunity(ts + 10, 2, 120.0))

    profitable = load_recent_profitable(5, db_session_factory=session_factory, db_path=db_path)
    assert len(profitable) == 2
    assert profitable[0]["triangle"]["id"] == 2  # Last appended first
    assert profitable[0]["profit_absolute"] > profitable[1]["profit_absolute"]

    top_hours = load_top_per_hour(2, db_session_factory=session_factory, db_path=db_path)
    assert len(top_hours) == 1
    records = top_hours[0]["records"]
    assert len(records) == 2
    assert records[0]["triangle"]["id"] == 2
