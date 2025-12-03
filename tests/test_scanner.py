from src.arb.market_graph import Edge, Triangle
from src.arb.orderbook_cache import OrderbookCache
from src.arb.triangular_scanner import TriangularScanner
from src.config.models import TradingSettings


def test_triangle_edge_positive():
    trading = TradingSettings(
        quote_asset="USDC",
        initial_quote_balance=10000,
        min_position_size=10,
        max_position_size=100,
        min_edge_threshold=0.0,
        safety_slippage_buffer=0.0,
        max_concurrent_triangles=5,
    )
    cache = OrderbookCache()
    cache.apply_snapshot("USDC/BTC", bids=[(100, 10)], asks=[(100, 10)])
    cache.apply_snapshot("BTC/ETH", bids=[(2, 10)], asks=[(2, 10)])
    cache.apply_snapshot("ETH/USDC", bids=[(60, 10)], asks=[(60, 10)])

    tri = Triangle(
        id=1,
        assets=("USDC", "BTC", "ETH"),
        edges=(Edge("USDC", "BTC", "USDC/BTC"), Edge("BTC", "ETH", "BTC/ETH"), Edge("ETH", "USDC", "ETH/USDC")),
    )
    scanner = TriangularScanner([tri], cache, trading)
    opp = scanner.evaluate_triangle(tri, 10)
    assert opp is not None
    assert opp.theoretical_final_amount > 0
