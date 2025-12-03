from src.arb.orderbook_cache import OrderbookCache


def test_effective_price():
    cache = OrderbookCache()
    cache.apply_snapshot("USDC/BTC", bids=[(30000, 1)], asks=[(31000, 1)])
    avg_price, slippage, insufficient = cache.get_effective_price("USDC/BTC", "buy", 0.5)
    assert not insufficient
    assert avg_price == 31000
    assert slippage == 0
