from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.arb.triangular_scanner import Opportunity
from src.core.logging import get_logger
from src.db.models import Base, TriangularOpportunity

logger = get_logger(__name__)

DEFAULT_DB_PATH = os.getenv("DB_PATH", "data/arb_bot.sqlite")
TOP_PER_HOUR_LIMIT = int(os.getenv("TOP_N_PER_HOUR", "20"))


def _build_session_factory(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def session_scope():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    return session_scope


def _row_to_payload(row: TriangularOpportunity) -> Dict:
    return {
        "id": row.id,
        "timestamp": row.timestamp,
        "triangle": {"id": row.triangle_id, "assets": (row.asset_a, row.asset_b, row.asset_c)},
        "initial_size": row.initial_size,
        "theoretical_final_amount": row.theoretical_final_amount,
        "profit_absolute": row.profit_absolute,
        "profit_percent": row.profit_percent,
        "prices": (row.price_leg1, row.price_leg2, row.price_leg3),
    }


class ProfitRecorder:
    def __init__(self, db_session_factory=None, db_path: Optional[str] = None):
        if db_session_factory:
            self.db_session_factory = db_session_factory
        else:
            self.db_session_factory = _build_session_factory(db_path or DEFAULT_DB_PATH)

    async def record_opportunity_async(self, opp: Opportunity) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.record_opportunity, opp)

    def record_opportunity(self, opp: Opportunity) -> None:
        try:
            ts_str, ts_unix = self._format_timestamp(opp.timestamp)
            with self.db_session_factory() as session:
                session.add(
                    TriangularOpportunity(
                        triangle_id=opp.triangle_id,
                        timestamp=ts_str,
                        timestamp_unix=ts_unix,
                        asset_a=opp.assets[0],
                        asset_b=opp.assets[1],
                        asset_c=opp.assets[2],
                        price_leg1=opp.prices[0],
                        price_leg2=opp.prices[1],
                        price_leg3=opp.prices[2],
                        initial_size=opp.initial_size,
                        theoretical_final_amount=opp.theoretical_final_amount,
                        theoretical_edge=opp.theoretical_edge,
                        profit_absolute=opp.profit_absolute,
                        profit_percent=opp.profit_percent,
                    )
                )
                session.commit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to persist profitable opportunity: %s", exc)

    def _format_timestamp(self, ts: float) -> tuple[str, float]:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.timestamp()


def _get_factory(session_factory=None, db_path: Optional[str] = None):
    if session_factory:
        return session_factory
    return _build_session_factory(db_path or DEFAULT_DB_PATH)


def load_recent_profitable(limit: int, db_session_factory=None, db_path: Optional[str] = None) -> List[Dict]:
    factory = _get_factory(db_session_factory, db_path)
    with factory() as session:
        rows = (
            session.query(TriangularOpportunity)
            .order_by(TriangularOpportunity.id.desc())
            .limit(limit)
            .all()
        )
        return [_row_to_payload(r) for r in rows]


def load_top_per_hour(hours: int, db_session_factory=None, db_path: Optional[str] = None) -> List[Dict]:
    factory = _get_factory(db_session_factory, db_path)
    earliest = (datetime.now(timezone.utc) - timedelta(hours=hours - 1)).timestamp()
    with factory() as session:
        rows = (
            session.query(TriangularOpportunity)
            .filter(TriangularOpportunity.timestamp_unix >= earliest)
            .all()
        )

    grouped: Dict[str, List[TriangularOpportunity]] = {}
    for row in rows:
        hour_key = datetime.fromtimestamp(row.timestamp_unix, tz=timezone.utc).strftime("%Y-%m-%d %H")
        grouped.setdefault(hour_key, []).append(row)

    results: List[Dict] = []
    for hour_key, entries in grouped.items():
        sorted_entries = sorted(entries, key=lambda r: r.profit_absolute or 0.0, reverse=True)
        results.append({"hour": hour_key, "records": [_row_to_payload(r) for r in sorted_entries[:TOP_PER_HOUR_LIMIT]]})

    results.sort(key=lambda e: e.get("hour"), reverse=True)
    return results
