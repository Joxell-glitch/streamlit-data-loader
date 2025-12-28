from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Dict, Optional, Tuple

from src.arb.orderbook_cache import OrderbookCache
from src.arb.triangular_scanner import Opportunity
from src.config.models import TradingSettings
from src.core.logging import get_logger
from src.db.models import Opportunity as OpportunityModel, PaperTrade, PortfolioSnapshot, RunMetadata
from src.db.session import get_session
from src.utils.session_scope import session_scope

logger = get_logger(__name__)

FEE_RATE = 0.001  # placeholder taker fee


def default_portfolio(quote_asset: str, initial_quote_balance: float) -> Dict[str, float]:
    return {quote_asset: initial_quote_balance}


@dataclass
class ExecutionResult:
    realized_final_amount: float
    realized_edge: float
    realized_pnl: float
    slippage: Tuple[float, float, float]
    fees: Tuple[float, float, float]


class PaperTrader:
    def __init__(self, orderbooks: OrderbookCache, settings: TradingSettings, run_id: str, db_session_factory=get_session):
        self.orderbooks = orderbooks
        self.settings = settings
        self.run_id = run_id
        self.db_session_factory = db_session_factory
        self.portfolio = default_portfolio(settings.quote_asset, settings.initial_quote_balance)
        self._queue: asyncio.Queue[Optional[Opportunity]] = asyncio.Queue()
        self.running = False

    async def start(self):
        self.running = True
        while self.running:
            opp = await self._queue.get()
            if opp is None:
                continue
            try:
                await self.handle_opportunity(opp)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Failed to handle opportunity: %s", exc)

    async def enqueue(self, opp: Opportunity) -> None:
        await self._queue.put(opp)

    def stop(self) -> None:
        self.running = False
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:  # pragma: no cover - defensive
            pass

    def _enough_balance(self, required: float) -> bool:
        return self.portfolio.get(self.settings.quote_asset, 0.0) >= required

    def _apply_fee(self, amount: float) -> float:
        return amount * (1 - FEE_RATE)

    async def handle_opportunity(self, opp: Opportunity) -> None:
        with session_scope(self.db_session_factory) as s:
            s.add(
                OpportunityModel(
                    run_id=self.run_id,
                    timestamp=opp.timestamp,
                    triangle_id=opp.triangle_id,
                    asset_a=opp.assets[0],
                    asset_b=opp.assets[1],
                    asset_c=opp.assets[2],
                    initial_size=opp.initial_size,
                    theoretical_final_amount=opp.theoretical_final_amount,
                    theoretical_edge=opp.theoretical_edge,
                    estimated_slippage_leg1=opp.slippage[0],
                    estimated_slippage_leg2=opp.slippage[1],
                    estimated_slippage_leg3=opp.slippage[2],
                    parameters_snapshot={},
                )
            )
            s.commit()

        if not self._enough_balance(opp.initial_size):
            self._record_trade(opp, None, executed=False, reason="insufficient balance")
            return

        position_size = min(opp.initial_size, self.settings.max_position_size)
        execution = self._simulate_execution(opp, position_size)
        self._record_trade(opp, execution, executed=True, reason=None)

    def _simulate_execution(self, opp: Opportunity, size: float) -> ExecutionResult:
        quote = self.settings.quote_asset
        balance_quote = self.portfolio.get(quote, 0.0)
        balance_quote -= size

        leg1_price, sl1, _ = self.orderbooks.get_effective_price(f"{quote}/{opp.assets[1]}", "buy", size)
        asset_b = size / leg1_price if leg1_price else 0.0
        fees1 = size * FEE_RATE

        leg2_price, sl2, _ = self.orderbooks.get_effective_price(f"{quote}/{opp.assets[2]}", "buy", asset_b)
        asset_c = asset_b / leg2_price if leg2_price else 0.0
        fees2 = asset_b * leg2_price * FEE_RATE

        leg3_price, sl3, _ = self.orderbooks.get_effective_price(f"{quote}/{opp.assets[0]}", "sell", asset_c)
        final_quote = asset_c * leg3_price
        fees3 = final_quote * FEE_RATE

        final_quote_after_fees = final_quote - fees1 - fees2 - fees3
        self.portfolio[quote] = balance_quote + final_quote_after_fees
        realized_pnl = final_quote_after_fees - size
        edge = realized_pnl / size if size else 0.0

        return ExecutionResult(
            realized_final_amount=final_quote_after_fees,
            realized_edge=edge,
            realized_pnl=realized_pnl,
            slippage=(sl1, sl2, sl3),
            fees=(fees1, fees2, fees3),
        )

    def _record_trade(self, opp: Opportunity, execution: Optional[ExecutionResult], executed: bool, reason: Optional[str]) -> None:
        with session_scope(self.db_session_factory) as s:
            s.add(
                PaperTrade(
                    run_id=self.run_id,
                    timestamp=time.time(),
                    triangle_id=opp.triangle_id,
                    initial_size=opp.initial_size,
                    realized_final_amount=execution.realized_final_amount if execution else 0.0,
                    realized_pnl=execution.realized_pnl if execution else 0.0,
                    realized_edge=execution.realized_edge if execution else 0.0,
                    realized_slippage_leg1=execution.slippage[0] if execution else 0.0,
                    realized_slippage_leg2=execution.slippage[1] if execution else 0.0,
                    realized_slippage_leg3=execution.slippage[2] if execution else 0.0,
                    fees_paid_leg1=execution.fees[0] if execution else 0.0,
                    fees_paid_leg2=execution.fees[1] if execution else 0.0,
                    fees_paid_leg3=execution.fees[2] if execution else 0.0,
                    was_executed=executed,
                    reason_if_not_executed=reason,
                )
            )
            s.add(
                PortfolioSnapshot(
                    run_id=self.run_id,
                    timestamp=time.time(),
                    balances=self.portfolio.copy(),
                    total_value_in_quote=self.portfolio.get(self.settings.quote_asset, 0.0),
                )
            )
            s.commit()
