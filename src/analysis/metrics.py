from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from src.db.models import Opportunity, PaperTrade, PortfolioSnapshot
from src.db.session import get_session


def load_trades(run_id: str):
    session_factory = get_session()
    with session_factory() as s:
        trades = s.execute(select(PaperTrade).where(PaperTrade.run_id == run_id)).scalars().all()
    return trades


def load_snapshots(run_id: str):
    session_factory = get_session()
    with session_factory() as s:
        snaps = s.execute(select(PortfolioSnapshot).where(PortfolioSnapshot.run_id == run_id)).scalars().all()
    return snaps


def pnl_summary(trades) -> dict:
    df = pd.DataFrame([{
        "pnl": t.realized_pnl,
        "triangle": t.triangle_id,
        "edge": t.realized_edge,
        "timestamp": t.timestamp,
    } for t in trades])
    if df.empty:
        return {"total_pnl": 0.0, "by_triangle": {}, "edge_distribution": [], "trade_count": 0}
    summary = {
        "total_pnl": df["pnl"].sum(),
        "by_triangle": df.groupby("triangle")["pnl"].sum().to_dict(),
        "edge_distribution": df["edge"].describe().to_dict(),
        "trade_count": len(df),
    }
    return summary


def drawdown(snaps) -> float:
    if not snaps:
        return 0.0
    values = [s.total_value_in_quote for s in snaps]
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        drawdown = (peak - v) / peak if peak else 0.0
        max_dd = max(max_dd, drawdown)
    return max_dd


def compute_metrics(run_id: str) -> dict:
    trades = load_trades(run_id)
    snaps = load_snapshots(run_id)
    summary = pnl_summary(trades)
    dd = drawdown(snaps)
    trade_freq = summary["trade_count"] / max((snaps[-1].timestamp - snaps[0].timestamp) / 3600, 1) if snaps else 0
    return {
        "pnl_summary": summary,
        "max_drawdown": dd,
        "trade_frequency_per_hour": trade_freq,
    }
