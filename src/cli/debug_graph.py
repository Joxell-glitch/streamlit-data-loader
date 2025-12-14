from __future__ import annotations

import asyncio

import typer

from src.arb.market_graph import MarketGraph
from src.config.loader import load_config
from src.core.logging import get_logger, setup_logging
from src.hyperliquid_client.client import HyperliquidClient


app = typer.Typer(add_completion=False)
logger = get_logger(__name__)


@app.command()
def main(
    max_samples: int = typer.Option(10, help="Maximum number of edges to sample in logs"),
    config_path: str = typer.Option("config/config.yaml", help="Path to configuration file"),
):    
    settings = load_config(config_path)
    setup_logging(settings.logging)
    logger.info("[GRAPH] debug_graph_cli starting max_samples=%s", max_samples)

    async def _run():
        client = HyperliquidClient(settings.api, settings.network)
        try:
            spot_meta = await client.fetch_spot_meta()
            market_graph = MarketGraph(settings)
            market_graph.build_from_spot_meta(spot_meta, max_sample_edges=max_samples)
            build_stats = market_graph.last_build_stats or {}
            triangle_stats = market_graph.last_triangle_stats or {}
            typer.echo(
                "Graph debug summary -> markets_total={mt} markets_used={mu} nodes={n} edges={e} triangles={t}".format(
                    mt=build_stats.get("markets_total"),
                    mu=build_stats.get("markets_used"),
                    n=len(market_graph.assets),
                    e=len(market_graph.edges),
                    t=triangle_stats.get("triangles_total", len(market_graph.triangles)),
                )
            )
        finally:
            await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
