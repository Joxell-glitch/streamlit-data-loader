from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OrderbookSide:
    levels: List[Tuple[float, float]] = field(default_factory=list)  # (price, size)

    def update(self, levels: List[Tuple[float, float]]) -> None:
        self.levels = levels

    def best_price(self, side: str) -> float:
        if not self.levels:
            return 0.0
        return self.levels[0][0]


@dataclass
class Orderbook:
    bids: OrderbookSide = field(default_factory=OrderbookSide)
    asks: OrderbookSide = field(default_factory=OrderbookSide)


class OrderbookCache:
    def __init__(self) -> None:
        self.books: Dict[str, Orderbook] = {}

    @staticmethod
    def _normalize_level(level: object) -> Optional[Tuple[float, float]]:
        if isinstance(level, dict):
            px = level.get("px") or level.get("price")
            sz = level.get("sz") or level.get("size")
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            px, sz = level[0], level[1]
        else:
            return None

        try:
            price = float(px)
            size = float(sz)
        except (TypeError, ValueError):
            return None

        return price, size

    def _normalize_side(self, levels: object) -> List[Tuple[float, float]]:
        if not isinstance(levels, (list, tuple)):
            return []

        normalized_levels: List[Tuple[float, float]] = []
        for level in levels:
            normalized_level = self._normalize_level(level)
            if normalized_level is not None:
                normalized_levels.append(normalized_level)
        return normalized_levels

    def apply_snapshot(self, pair: str, bids: List[object], asks: List[object]) -> None:
        normalized_bids = self._normalize_side(bids)
        normalized_asks = self._normalize_side(asks)

        discarded_bids = (len(bids) if isinstance(bids, (list, tuple)) else 1) - len(normalized_bids)
        discarded_asks = (len(asks) if isinstance(asks, (list, tuple)) else 1) - len(normalized_asks)

        if discarded_bids > 0:
            logger.debug("Discarded %s invalid bid levels for %s", discarded_bids, pair)
        if discarded_asks > 0:
            logger.debug("Discarded %s invalid ask levels for %s", discarded_asks, pair)

        sorted_bids = sorted(normalized_bids, key=lambda x: x[0], reverse=True)
        sorted_asks = sorted(normalized_asks, key=lambda x: x[0])

        book = self.books.setdefault(pair, Orderbook())
        book.bids.update(sorted_bids)
        book.asks.update(sorted_asks)

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
        top_price = levels[0][0]
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
