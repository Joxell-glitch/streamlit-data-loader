from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from src.arb.market_graph import Triangle
from src.arb.orderbook_cache import OrderbookCache
from src.config.models import TradingSettings
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


class TriangularScanner:
    def __init__(self, triangles: Iterable[Triangle], orderbooks: OrderbookCache, settings: TradingSettings):
        self.triangles = list(triangles)
        self.orderbooks = orderbooks
        self.settings = settings
        self.running = False

    async def run(self, interval_ms: int, callback, stop_event: Optional[asyncio.Event] = None) -> None:
        self.running = True
        while self.running and (not stop_event or not stop_event.is_set()):
            for triangle in self.triangles:
                opp = self.evaluate_triangle(triangle, self.settings.min_position_size)
                if opp and opp.theoretical_edge >= self.settings.min_edge_threshold + self.settings.safety_slippage_buffer:
                    await callback(opp)
            await asyncio.sleep(interval_ms / 1000)

    def stop(self) -> None:
        self.running = False

    def evaluate_triangle(self, triangle: Triangle, amount_quote: float) -> Optional[Opportunity]:
        a, b, c = triangle.assets
        leg1_pair = triangle.edges[0].pair
        leg2_pair = triangle.edges[1].pair
        leg3_pair = triangle.edges[2].pair

        # Leg1: A -> B (using quote asset -> coin)
        price1, sl1, insufficient1 = self.orderbooks.get_effective_price(leg1_pair, "buy", amount_quote)
        if insufficient1 or price1 <= 0:
            return None
        amount_b = amount_quote / price1

        # Leg2: B -> C (sell B for quote, then buy C?) assume B -> C uses quote asset as intermediate; simplified by using same pair
        price2, sl2, insufficient2 = self.orderbooks.get_effective_price(leg2_pair, "buy", amount_b)
        if insufficient2 or price2 <= 0:
            return None
        amount_c = amount_b / price2

        price3, sl3, insufficient3 = self.orderbooks.get_effective_price(leg3_pair, "sell", amount_c)
        if insufficient3 or price3 <= 0:
            return None
        final_amount = amount_c * price3

        edge = (final_amount / amount_quote) - 1
        return Opportunity(
            triangle_id=triangle.id,
            assets=triangle.assets,
            timestamp=time.time(),
            initial_size=amount_quote,
            theoretical_final_amount=final_amount,
            theoretical_edge=edge,
            slippage=(sl1, sl2, sl3),
        )
