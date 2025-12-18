from __future__ import annotations

import asyncio
import argparse
import logging
import os
from typing import Optional

from src.config.loader import load_config
from src.core.logging import get_logger, setup_logging
from src.db.session import get_session, init_db
from src.hyperliquid_client.client import HyperliquidClient
from src.strategy.spot_perp_paper import SpotPerpPaperEngine
from src.db.models import SpotPerpOpportunity
from src.observability.feed_health import FeedHealthTracker

logger = get_logger(__name__)


async def _run_engine(config_path: str, debug_feeds: bool = False, assets_arg: Optional[str] = None) -> None:
    settings = load_config(config_path)
    setup_logging(settings.logging)

    if debug_feeds:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        for handler in root_logger.handlers:
            handler.setLevel(logging.DEBUG)
        logging.getLogger("src.strategy.spot_perp_paper").setLevel(logging.DEBUG)
        logging.getLogger("src.hyperliquid_client.client").setLevel(logging.DEBUG)
    init_db(settings)
    if settings.database.backend == "sqlite":
        db_path = settings.database.sqlite_path
        logger.info(
            "SQLite database path resolved to %s (exists=%s)",
            db_path,
            os.path.exists(db_path),
        )

    assets = [a.strip().upper() for a in assets_arg.split(",") if a.strip()] if assets_arg else ["BTC"]
    logger.info("Starting spot-perp paper engine for assets: %s", ", ".join(assets))

    feed_health = FeedHealthTracker(settings.observability.feed_health)
    client = HyperliquidClient(settings.api, settings.network, feed_health_tracker=feed_health)
    if not settings.validation.enabled:
        logger.info("[VALIDATION] config disabled; forcing runtime validation harness on")
        settings.validation.enabled = True
    session_factory = get_session(settings)
    engine = SpotPerpPaperEngine(
        client,
        assets,
        settings.trading,
        db_session_factory=session_factory,
        feed_health_settings=settings.observability.feed_health,
        feed_health_tracker=feed_health,
        validation_settings=settings.validation,
    )

    stop_event = asyncio.Event()
    try:
        await engine.run_forever(stop_event=stop_event)
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        logger.info("Keyboard interrupt received, shutting down spot-perp engine")
        stop_event.set()
    finally:
        await engine.shutdown()  # log summary and stop background tasks if still running
        await client.close()
        logger.info("Spot-perp paper engine stopped")


def main(config_path: Optional[str] = "config/config.yaml") -> None:
    parser = argparse.ArgumentParser(description="Run spot-perp paper engine")
    parser.add_argument("--config", default=config_path, help="Path to config YAML file")
    parser.add_argument(
        "--debug-feeds",
        action="store_true",
        help="Enable verbose debug logging for spot/perp feed handling",
    )
    parser.add_argument(
        "--assets",
        default=None,
        help="Comma-separated list of asset symbols to track (e.g. BTC,ETH,SOL)",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Log a health/status snapshot without starting the trading engine",
    )
    args = parser.parse_args()

    if args.status_only:
        settings = load_config(args.config)
        setup_logging(settings.logging)
        init_db(settings)
        logger.info("[STATUS_ONLY] config=%s network=%s", args.config, settings.network)
        if settings.database.backend == "sqlite":
            logger.info("[STATUS_ONLY] sqlite_path=%s exists=%s", settings.database.sqlite_path, os.path.exists(settings.database.sqlite_path))
            if os.path.exists(settings.database.sqlite_path):
                logger.info(
                    "[STATUS_ONLY] sqlite_size_kb=%.2f", os.path.getsize(settings.database.sqlite_path) / 1024
                )
        session_factory = get_session(settings)
        with session_factory() as session:
            opp_count = session.query(SpotPerpOpportunity).count()
        logger.info("[STATUS_ONLY] spot_perp_opportunities=%s", opp_count)
        logger.info(
            "[STATUS_ONLY] assets=%s heartbeat_interval=%ss metrics_interval=%ss",
            args.assets or "BTC",
            10,
            os.getenv("SPOT_PERP_METRICS_INTERVAL", "30"),
        )
        return

    asyncio.run(_run_engine(args.config, debug_feeds=args.debug_feeds, assets_arg=args.assets))


if __name__ == "__main__":
    main()
