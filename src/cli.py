from __future__ import annotations

import asyncio
import time
import uuid
from typing import Dict, Optional

import typer

from src.analysis.report import generate_report
from src.config.loader import load_config
from src.core.logging import setup_logging, get_logger
from src.db.session import get_session, init_db
from src.db.runtime_status import get_runtime_status, update_runtime_status
from src.hyperliquid_client.client import HyperliquidClient
from src.arb.market_graph import MarketGraph
from src.arb.orderbook_cache import OrderbookCache
from src.arb.triangular_scanner import TriangularScanner
from src.arb.paper_trader import PaperTrader
from src.arb.profit_persistence import ProfitRecorder

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
def run_paper_bot(config_path: str = typer.Option("config/config.yaml"), run_id: Optional[str] = typer.Option(None)):
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
        session_factory = get_session(settings)
        profit_recorder = ProfitRecorder(db_session_factory=session_factory)

        def _update_status(**fields):
            session = session_factory()
            with session as s:
                update_runtime_status(s, **fields)

        def _get_status():
            session = session_factory()
            with session as s:
                return get_runtime_status(s)

        _update_status(bot_running=True, ws_connected=False, last_heartbeat=time.time())

        stop_event = asyncio.Event()

        trader = PaperTrader(orderbooks, settings.trading, run_id, db_session_factory=session_factory)
        scanner = TriangularScanner(
            market_graph.triangles, orderbooks, settings.trading, settings.observability
        )
        asset_pair_map: Dict[str, str] = {}
        for edge in market_graph.edges:
            if edge.quote != settings.trading.quote_asset:
                continue
            asset_pair_map.setdefault(edge.base, edge.pair)
        symbol_map = {asset: asset for asset in asset_pair_map}

        def _on_orderbook(kind, asset, snapshot):
            pair = asset_pair_map.get(asset)
            if not pair:
                return
            bids = snapshot.get("bids", []) if isinstance(snapshot, dict) else []
            asks = snapshot.get("asks", []) if isinstance(snapshot, dict) else []
            orderbooks.apply_snapshot(pair, bids, asks)

        client.add_orderbook_listener(_on_orderbook)

        async def ws_listener():
            backoff = 1
            while not stop_event.is_set():
                try:
                    await client.connect_ws()
                    backoff = 1
                    _update_status(ws_connected=True)
                    await client.subscribe_orderbooks(symbol_map, kind="spot")
                    await client.subscribe_mark_prices(symbol_map)
                    await stop_event.wait()
                    break
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("WebSocket listener error: %s", exc)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                finally:
                    _update_status(ws_connected=False)

        async def scanner_task():
            async def _handle_profitable(opp):
                await profit_recorder.record_opportunity_async(opp)
                await trader.enqueue(opp)

            await scanner.run(500, _handle_profitable, stop_event=stop_event)

        async def heartbeat_task():
            while not stop_event.is_set():
                status = _get_status()
                if status and not status.bot_enabled:
                    logger.info("Bot disabled via runtime_status, shutting down")
                    stop_event.set()
                    break
                _update_status(bot_running=True, last_heartbeat=time.time())
                await asyncio.sleep(5)

        tasks = [
            asyncio.create_task(trader.start()),
            asyncio.create_task(ws_listener()),
            asyncio.create_task(scanner_task()),
            asyncio.create_task(heartbeat_task()),
        ]

        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop_event.set()
            scanner.stop()
            trader.stop()
            await client.close()
            _update_status(bot_running=False, ws_connected=False, last_heartbeat=time.time())
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(_run())


@app.command()
def analyze_run(run_id: str = typer.Option(..., help="Run ID"), config_path: str = typer.Option("config/config.yaml"), output_dir: str = typer.Option("analysis_output")):
    settings = load_config(config_path)
    setup_logging(settings.logging)
    result = generate_report(run_id, output_dir)
    typer.echo(f"Report written to {result['report_path']}, recommendations to {result['recommendations_path']}")


if __name__ == "__main__":
    app()
