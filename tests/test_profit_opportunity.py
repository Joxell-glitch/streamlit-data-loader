from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.arb.profit_persistence import save_profit_opportunity
from src.arb.triangular_scanner import Opportunity
from src.db.models import Base, ProfitOpportunity


def _session_factory(tmp_path):
    db_path = tmp_path / "arb_bot.sqlite"
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

    return scope


def _opportunity(profit: float) -> Opportunity:
    ts = datetime.now(timezone.utc).timestamp()
    edge = (100.0 + profit) / 100.0 - 1
    return Opportunity(
        triangle_id=123,
        assets=("A", "B", "C"),
        timestamp=ts,
        initial_size=100.0,
        theoretical_final_amount=100.0 + profit,
        theoretical_edge=edge,
        slippage=(0.0, 0.0, 0.0),
        prices=(1.0, 1.0, 1.0),
        profit_absolute=profit,
        profit_percent=edge * 100,
    )


def test_save_profit_opportunity(tmp_path):
    session_factory = _session_factory(tmp_path)
    opportunity = _opportunity(5.0)

    save_profit_opportunity(session_factory, opportunity)

    with session_factory() as session:
        stored = session.query(ProfitOpportunity).all()

    assert len(stored) == 1
    assert stored[0].triangle_id == opportunity.triangle_id
    assert stored[0].profit == opportunity.profit_absolute
    assert stored[0].timestamp.replace(microsecond=0) == datetime.fromtimestamp(
        opportunity.timestamp
    ).replace(microsecond=0)
