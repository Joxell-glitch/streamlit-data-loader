from src.arb.market_graph import MarketGraph
from src.config.models import (
    APISettings,
    DatabaseSettings,
    LoggingSettings,
    ObservabilitySettings,
    Settings,
    TradingSettings,
)


def make_settings():
    return Settings(
        network="testnet",
        api=APISettings("", "", "", "", ""),
        trading=TradingSettings(
            quote_asset="USDC",
            initial_quote_balance=10000,
            min_position_size=10,
            max_position_size=100,
            min_edge_threshold=0.001,
            safety_slippage_buffer=0.0,
            max_concurrent_triangles=5,
        ),
        database=DatabaseSettings(backend="sqlite", sqlite_path=":memory:"),
        logging=LoggingSettings(level="INFO", log_file="/tmp/test.log"),
        observability=ObservabilitySettings(),
    )


def test_triangle_generation():
    mg = MarketGraph(make_settings())
    spot_meta = {"universe": [
        {"base": "USDC", "quote": "BTC"},
        {"base": "BTC", "quote": "ETH"},
        {"base": "ETH", "quote": "USDC"},
    ]}
    mg.build_from_spot_meta(spot_meta)
    assert len(mg.triangles) > 0


def test_hyperliquid_parsing_accepts_single_symbol_markets():
    settings = make_settings()
    settings.api.rest_base = "https://api.hyperliquid.xyz"
    settings.trading.whitelist = ["USDC"]

    mg = MarketGraph(settings)
    spot_meta = {"universe": [
        {"name": "BTC"},
        {"coin": "ETH"},
        {"symbol": "SOL"},
    ]}

    mg.build_from_spot_meta(spot_meta)

    edge_pairs = {(e.base, e.quote) for e in mg.edges}
    assert ("BTC", "USDC") in edge_pairs
    assert ("USDC", "BTC") in edge_pairs
    assert ("ETH", "USDC") in edge_pairs
    assert mg.last_build_stats.get("skipped_whitelist") == 0
    assert mg.last_build_stats.get("markets_used") == 3
