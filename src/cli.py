from __future__ import annotations

import asyncio
import time
import uuid

import typer

from src.analysis.report import generate_report
from src.config.loader import load_config
from src.core.logging import setup_logging, get_logger
from src.db.session import init_db
from src.hyperliquid_client.client import HyperliquidClient
from src.arb.market_graph import MarketGraph
from src.arb.orderbook_cache import OrderbookCache
from src.arb.triangular_scanner import TriangularScanner
from src.arb.paper_trader import PaperTrader

app = typer.Typer(add_completion=False)
logger = get_logger(__name__)


@app.command()
def init_db_cmd(config_path: str = typer.Option("config/config.yaml", help="Path to config")):
    settings = load_config(config_path)
    setup_logging(settings.logging)
    init_db(settings)
    typer.echo("Database initialized")


@app.command()
def measure_latency(config_path: str = typer.Option("config/config.yaml")):
    settings = load_config(config_path)
    setup_logging(settings.logging)
    client = HyperliquidClient(settings.api, settings.network)

    async def _measure():
        latencies = []
        for _ in range(3):
            start = time.time()
            await client.fetch_info()
            latencies.append((time.time() - start) * 1000)
        await client.close()
        typer.echo(f"Latency ms min/avg/max: {min(latencies):.2f}/{sum(latencies)/len(latencies):.2f}/{max(latencies):.2f}")

    asyncio.run(_measure())


@app.command()
def run_paper_bot(config_path: str = typer.Option("config/config.yaml"), run_id: str | None = typer.Option(None)):
    settings = load_config(config_path)
    setup_logging(settings.logging)
    run_id = run_id or str(uuid.uuid4())
    typer.echo(f"Starting run {run_id}")

    async def _run():
        client = HyperliquidClient(settings.api, settings.network)
        orderbooks = OrderbookCache()
        market_graph = MarketGraph(settings)
        spot_meta = await client.fetch_spot_meta()
        market_graph.build_from_spot_meta(spot_meta)
        await client.connect_ws()
        await client.subscribe_orderbooks([e.quote for e in market_graph.edges if e.base == settings.trading.quote_asset])

        trader = PaperTrader(orderbooks, settings.trading, run_id)
        scanner = TriangularScanner(market_graph.triangles, orderbooks, settings.trading)

        async def ws_listener():
            async for msg in client.ws_messages():
                if msg.get("type") == "l2Book":
                    coin = msg.get("coin")
                    pair = f"{settings.trading.quote_asset}/{coin}"
                    bids = msg.get("levels", {}).get("bids", [])
                    asks = msg.get("levels", {}).get("asks", [])
                    orderbooks.apply_snapshot(pair, bids, asks)

        async def scanner_task():
            await scanner.run(500, trader.enqueue)

        await asyncio.gather(trader.start(), ws_listener(), scanner_task())

    asyncio.run(_run())


@app.command()
def analyze_run(run_id: str = typer.Option(..., help="Run ID"), config_path: str = typer.Option("config/config.yaml"), output_dir: str = typer.Option("analysis_output")):
    settings = load_config(config_path)
    setup_logging(settings.logging)
    result = generate_report(run_id, output_dir)
    typer.echo(f"Report written to {result['report_path']}, recommendations to {result['recommendations_path']}")


if __name__ == "__main__":
    app()
