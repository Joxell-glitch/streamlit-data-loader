from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OrderbookSide:
    levels: List[Tuple[float, float]] = field(default_factory=list)  # (price, size)

    def update(self, levels: List[Tuple[float, float]]) -> None:
        self.levels = sorted(levels, key=lambda x: x[0], reverse=False)

    def best_price(self, side: str) -> float:
        if not self.levels:
            return 0.0
        return self.levels[0][0] if side == "ask" else self.levels[-1][0]


@dataclass
class Orderbook:
    bids: OrderbookSide = field(default_factory=OrderbookSide)
    asks: OrderbookSide = field(default_factory=OrderbookSide)


class OrderbookCache:
    def __init__(self) -> None:
        self.books: Dict[str, Orderbook] = {}

    def apply_snapshot(self, pair: str, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> None:
        book = self.books.setdefault(pair, Orderbook())
        book.bids.update(sorted(bids, key=lambda x: x[0], reverse=True))
        book.asks.update(sorted(asks, key=lambda x: x[0]))

    def get_effective_price(self, pair: str, side: str, size: float) -> Tuple[float, float, bool]:
        """
        Calculate the volume-weighted average price for consuming `size` on one side of the book.
        side: "buy" means consume asks; "sell" means consume bids.
        Returns (avg_price, slippage_pct, insufficient_liquidity)
        """
        if pair not in self.books:
            return 0.0, 0.0, True
        book = self.books[pair]
        levels = book.asks.levels if side == "buy" else book.bids.levels
        if not levels:
            return 0.0, 0.0, True

        remaining = size
        cost = 0.0
        top_price = levels[0][0] if side == "buy" else levels[0][0]
        for price, level_size in levels:
            trade_size = min(remaining, level_size)
            cost += trade_size * price
            remaining -= trade_size
            if remaining <= 1e-12:
                break
        insufficient = remaining > 1e-12
        filled_size = size - remaining
        avg_price = cost / filled_size if filled_size else 0.0
        slippage_pct = (avg_price - top_price) / top_price if top_price else 0.0
        return avg_price, slippage_pct, insufficient
