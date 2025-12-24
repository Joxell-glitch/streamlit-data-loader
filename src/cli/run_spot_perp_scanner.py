from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Optional

from src.cli.spot_perp_assets import select_auto_assets
from src.config.loader import load_config
from src.core.logging import get_logger, setup_logging
from src.hyperliquid_client.client import HyperliquidClient
from src.observability.feed_health import FeedHealthTracker
from src.scanner.spot_perp_scanner import SpotPerpScanner
from src.strategy.spot_perp_paper import SpotPerpPaperEngine

logger = get_logger(__name__)


async def _run_scanner(
    config_path: str,
    assets_arg: Optional[str],
    auto_assets: bool,
    auto_assets_n: int,
    once: bool,
    duration_seconds: Optional[int],
) -> None:
    settings = load_config(config_path)
    setup_logging(settings.logging)

    if auto_assets:
        logging.getLogger("src.cli.spot_perp_assets").setLevel(logging.INFO)

    feed_health = FeedHealthTracker(settings.observability.feed_health)
    client = HyperliquidClient(settings.api, settings.network, feed_health_tracker=feed_health)
    if assets_arg:
        assets = [asset.strip().upper() for asset in assets_arg.split(",") if asset.strip()]
    elif auto_assets:
        assets = await select_auto_assets(client, limit=auto_assets_n)
    else:
        assets = ["BTC"]

    engine = SpotPerpPaperEngine(
        client,
        assets=assets,
        trading=settings.trading,
        feed_health_settings=settings.observability.feed_health,
        feed_health_tracker=feed_health,
        evaluate_on_update=False,
    )
    scanner = SpotPerpScanner(
        client=client,
        engine=engine,
        settings=settings.scanner,
        assets=assets,
        auto_assets_enabled=auto_assets,
        auto_assets_n=auto_assets_n,
    )

    try:
        await scanner.run(once=once, duration_seconds=duration_seconds)
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        logger.info("Keyboard interrupt received, stopping spot-perp scanner")
    finally:
        await client.close()
        logger.info("Spot-perp scanner stopped")


def main(config_path: Optional[str] = "config/config.yaml") -> None:
    parser = argparse.ArgumentParser(description="Run spot-perp edge scanner")
    parser.add_argument("--config", default=config_path, help="Path to config YAML file")
    parser.add_argument("--assets", default=None, help="Comma-separated asset list")
    parser.add_argument("--auto-assets", action="store_true", help="Auto-select spot/perp assets")
    parser.add_argument("--auto-assets-n", type=int, default=15, help="Auto-assets limit")
    parser.add_argument("--once", action="store_true", help="Run a single scan cycle")
    parser.add_argument("--duration-seconds", type=int, default=None, help="Stop after N seconds")
    args = parser.parse_args()

    asyncio.run(
        _run_scanner(
            config_path=args.config,
            assets_arg=args.assets,
            auto_assets=args.auto_assets,
            auto_assets_n=args.auto_assets_n,
            once=args.once,
            duration_seconds=args.duration_seconds,
        )
    )


if __name__ == "__main__":
    main()
