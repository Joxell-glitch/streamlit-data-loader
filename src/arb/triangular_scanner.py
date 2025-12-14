from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from src.arb.market_graph import Triangle
from src.arb.orderbook_cache import OrderbookCache
from src.config.models import ObservabilitySettings, TradingSettings
from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Opportunity:
    triangle_id: int
    assets: Tuple[str, str, str]
    timestamp: float
    initial_size: float
    theoretical_final_amount: float
    theoretical_edge: float
    slippage: Tuple[float, float, float]
    prices: Tuple[float, float, float]
    profit_absolute: float
    profit_percent: float


@dataclass
class OpportunityLogEntry:
    timestamp: float
    triangle_id: Optional[int]
    route: str
    profit_percent: float
    reason: str


class TriangularScanner:
    def __init__(
        self,
        triangles: Iterable[Triangle],
        orderbooks: OrderbookCache,
        settings: TradingSettings,
        observability: Optional[ObservabilitySettings] = None,
    ):
        self.triangles = list(triangles)
        self.orderbooks = orderbooks
        self.settings = settings
        self.running = False
        self.observability = observability or ObservabilitySettings()
        self._topn_buffer: List[OpportunityLogEntry] = []
        self._last_topn_log_time: float = time.time()

    async def run(self, interval_ms: int, callback, stop_event: Optional[asyncio.Event] = None) -> None:
        self.running = True
        while self.running and (not stop_event or not stop_event.is_set()):
            profitable: List[Opportunity] = []
            for triangle in self.triangles:
                opp, reason = self._evaluate_triangle_full(triangle, self.settings.min_position_size)
                self._record_topn_candidate(triangle, opp, reason)
                if opp and opp.theoretical_edge >= self.settings.min_edge_threshold + self.settings.safety_slippage_buffer:
                    if opp.profit_absolute > 0:
                        profitable.append(opp)
            profitable.sort(key=lambda o: o.profit_absolute, reverse=True)
            for opp in profitable[: self.settings.top_n_opportunities]:
                await callback(opp)
            self._maybe_log_topn()
            await asyncio.sleep(interval_ms / 1000)

    def stop(self) -> None:
        self.running = False

    def evaluate_triangle(self, triangle: Triangle, amount_quote: float) -> Optional[Opportunity]:
        opp, _ = self._evaluate_triangle_full(triangle, amount_quote)
        return opp

    def _evaluate_triangle_full(self, triangle: Triangle, amount_quote: float) -> Tuple[Optional[Opportunity], str]:
        a, b, c = triangle.assets
        leg1_pair = triangle.edges[0].pair
        leg2_pair = triangle.edges[1].pair
        leg3_pair = triangle.edges[2].pair

        # Leg1: A -> B (using quote asset -> coin)
        price1, sl1, insufficient1 = self.orderbooks.get_effective_price(leg1_pair, "buy", amount_quote)
        if insufficient1 or price1 <= 0:
            return None, "missing_book"
        amount_b = amount_quote / price1

        # Leg2: B -> C (sell B for quote, then buy C?) assume B -> C uses quote asset as intermediate; simplified by using same pair
        price2, sl2, insufficient2 = self.orderbooks.get_effective_price(leg2_pair, "buy", amount_b)
        if insufficient2 or price2 <= 0:
            return None, "missing_book"
        amount_c = amount_b / price2

        price3, sl3, insufficient3 = self.orderbooks.get_effective_price(leg3_pair, "sell", amount_c)
        if insufficient3 or price3 <= 0:
            return None, "missing_book"
        final_amount = amount_c * price3

        edge = (final_amount / amount_quote) - 1
        profit_absolute = final_amount - amount_quote
        opp = Opportunity(
            triangle_id=triangle.id,
            assets=triangle.assets,
            timestamp=time.time(),
            initial_size=amount_quote,
            theoretical_final_amount=final_amount,
            theoretical_edge=edge,
            slippage=(sl1, sl2, sl3),
            prices=(price1, price2, price3),
            profit_absolute=profit_absolute,
            profit_percent=edge * 100,
        )

        threshold_edge = self.settings.min_edge_threshold + self.settings.safety_slippage_buffer
        reason = "ok" if opp.theoretical_edge >= threshold_edge and opp.profit_absolute > 0 else "below_threshold"
        return opp, reason

    def _record_topn_candidate(self, triangle: Triangle, opp: Optional[Opportunity], reason: str) -> None:
        route = self._format_route(triangle)
        profit_percent = opp.profit_percent if opp else 0.0
        entry = OpportunityLogEntry(
            timestamp=opp.timestamp if opp else time.time(),
            triangle_id=getattr(triangle, "id", None),
            route=route,
            profit_percent=profit_percent,
            reason=reason,
        )
        self._topn_buffer.append(entry)

    def _maybe_log_topn(self) -> None:
        now = time.time()
        if now - self._last_topn_log_time < self.observability.log_top_n_each_sec:
            return
        if not self._topn_buffer:
            self._last_topn_log_time = now
            return
        sorted_entries = sorted(self._topn_buffer, key=lambda e: e.profit_percent, reverse=True)
        for entry in sorted_entries[: self.observability.top_n]:
            if abs(entry.profit_percent) < self.observability.min_abs_profit_to_log:
                continue
            ts = datetime.fromtimestamp(entry.timestamp).strftime("%Y-%m-%d %H:%M:%S")
            triangle_id = entry.triangle_id if entry.triangle_id is not None else "?"
            logger.info(
                "[TOPN] %s triangle=%s route=%s profit=%.4f reason=%s",
                ts,
                triangle_id,
                entry.route,
                entry.profit_percent,
                entry.reason,
            )
        self._topn_buffer.clear()
        self._last_topn_log_time = now

    @staticmethod
    def _format_route(triangle: Optional[Triangle]) -> str:
        try:
            pairs = [edge.pair for edge in triangle.edges]
            return "->".join(pairs)
        except Exception:
            return "?"
