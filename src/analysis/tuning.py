from __future__ import annotations

import numpy as np
from sqlalchemy import select

from src.db.models import Opportunity, PaperTrade
from src.db.session import get_session


def load_data(run_id: str):
    session_factory = get_session()
    with session_factory() as s:
        opps = s.execute(select(Opportunity).where(Opportunity.run_id == run_id)).scalars().all()
        trades = s.execute(select(PaperTrade).where(PaperTrade.run_id == run_id)).scalars().all()
    return opps, trades


def evaluate_parameters(opps, min_edge: float, max_size: float, initial_quote: float = 10_000.0):
    balance = initial_quote
    pnl = 0.0
    max_dd = 0.0
    for opp in opps:
        if opp.theoretical_edge < min_edge:
            continue
        size = min(max_size, balance)
        if size <= 0:
            continue
        final_amount = size * (1 + opp.theoretical_edge)
        pnl += final_amount - size
        balance += final_amount - size
        dd = max(0, (initial_quote - balance) / initial_quote)
        max_dd = max(max_dd, dd)
    return pnl, max_dd


def recommend_parameters(run_id: str) -> dict:
    opps, trades = load_data(run_id)
    if not opps:
        return {"recommended_min_edge_threshold": None, "recommended_max_position_size": None, "assets_to_blacklist": [], "summary_text": "No opportunities recorded."}
    min_edges = np.linspace(0.0005, 0.005, 5)
    max_sizes = np.linspace(50, 500, 5)
    best = None
    best_score = -1e9
    for me in min_edges:
        for ms in max_sizes:
            pnl, dd = evaluate_parameters(opps, me, ms)
            score = pnl - dd * 100  # penalize drawdown
            if score > best_score:
                best_score = score
                best = (me, ms, pnl, dd)
    assets = set()
    for t in trades:
        if t.realized_pnl < 0:
            assets.add(t.triangle_id)
    return {
        "recommended_min_edge_threshold": best[0] if best else None,
        "recommended_max_position_size": best[1] if best else None,
        "assets_to_blacklist": list(assets),
        "summary_text": f"Maximized score with min_edge={best[0]:.4f}, max_size={best[1]:.2f}, pnl={best[2]:.2f}, max_dd={best[3]:.2%}" if best else "Insufficient data.",
    }
