from __future__ import annotations

import asyncio
import argparse
import csv
import dataclasses
import logging
import os
import time
from typing import Optional

from src.config.loader import load_config
from src.core.logging import get_logger, setup_logging
from src.db.session import get_session, init_db
from src.hyperliquid_client.client import HyperliquidClient
from src.strategy.spot_perp_paper import SpotPerpDecision, SpotPerpPaperEngine
from src.strategy.spot_perp_scan import AssetScanMetrics, update_scan_metrics
from src.db.models import SpotPerpOpportunity
from src.observability.feed_health import FeedHealthTracker

logger = get_logger(__name__)

SCAN_WINDOW_SECONDS = 15


def _parse_assets_arg(assets_arg: Optional[str]) -> list[str]:
    if not assets_arg:
        return []
    return [a.strip().upper() for a in assets_arg.split(",") if a.strip()]


def _resolve_scan_assets(assets_arg: Optional[str], settings) -> list[str]:
    assets = _parse_assets_arg(assets_arg)
    if assets:
        return assets
    universe = [asset.strip().upper() for asset in getattr(settings.trading, "universe_assets", []) if asset.strip()]
    if universe:
        return universe
    raise ValueError(
        "Scan assets not provided. Pass --assets or populate trading.universe_assets in config/config.yaml."
    )


def _override_trading_fee_mode(trading, fee_mode: str):
    return dataclasses.replace(
        trading,
        fee_mode=fee_mode,
        spot_fee_mode=fee_mode,
        perp_fee_mode=fee_mode,
    )


def _format_scan_table(metrics: list[AssetScanMetrics], top_n: int) -> str:
    header = [
        "asset",
        "observations",
        "accept_count",
        "max_edge_bps",
        "max_effective_threshold_bps",
        "max_edge_minus_threshold_bps",
        "max_pnl_net_est",
        "best_fee_mode",
    ]
    rows = [
        [
            metric.asset,
            str(metric.observations),
            str(metric.accept_count),
            f"{metric.max_edge_bps:.2f}",
            f"{metric.max_effective_threshold_bps:.2f}",
            f"{metric.max_edge_minus_threshold_bps:.2f}",
            f"{metric.max_pnl_net_est:.6f}",
            metric.best_fee_mode,
        ]
        for metric in metrics[:top_n]
    ]
    widths = [max(len(row[i]) for row in [header] + rows) for i in range(len(header))]
    lines = [
        " | ".join(header[i].ljust(widths[i]) for i in range(len(header))),
        "-+-".join("-" * widths[i] for i in range(len(header))),
    ]
    for row in rows:
        lines.append(" | ".join(row[i].ljust(widths[i]) for i in range(len(header))))
    return "\n".join(lines)


def _write_scan_csv(path: str, metrics: list[AssetScanMetrics]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "asset",
                "observations",
                "accept_count",
                "max_edge_bps",
                "max_effective_threshold_bps",
                "max_edge_minus_threshold_bps",
                "max_pnl_net_est",
                "best_fee_mode",
            ]
        )
        for metric in metrics:
            writer.writerow(
                [
                    metric.asset,
                    metric.observations,
                    metric.accept_count,
                    f"{metric.max_edge_bps:.2f}",
                    f"{metric.max_effective_threshold_bps:.2f}",
                    f"{metric.max_edge_minus_threshold_bps:.2f}",
                    f"{metric.max_pnl_net_est:.6f}",
                    metric.best_fee_mode,
                ]
            )


def _finalize_scan_metrics(metrics_by_asset: dict[str, AssetScanMetrics]) -> list[AssetScanMetrics]:
    finalized = []
    for metric in metrics_by_asset.values():
        metric.max_edge_bps = metric.max_edge_bps or 0.0
        metric.max_effective_threshold_bps = metric.max_effective_threshold_bps or 0.0
        metric.max_edge_minus_threshold_bps = metric.max_edge_minus_threshold_bps or 0.0
        metric.max_pnl_net_est = metric.max_pnl_net_est or 0.0
        finalized.append(metric)
    finalized.sort(
        key=lambda metric: (metric.max_edge_minus_threshold_bps, metric.max_pnl_net_est), reverse=True
    )
    return finalized


async def _run_engine(
    config_path: str,
    debug_feeds: bool = False,
    assets_arg: Optional[str] = None,
    would_trade_override: Optional[bool] = None,
    trace_every_seconds_override: Optional[int] = None,
    fee_mode: Optional[str] = None,
) -> None:
    settings = load_config(config_path)
    setup_logging(settings.logging)
    init_db(settings)

    if would_trade_override is not None:
        settings.strategy.would_trade = would_trade_override
    if trace_every_seconds_override is not None:
        settings.strategy.trace_every_seconds = trace_every_seconds_override
    if fee_mode in {"maker", "taker"}:
        settings.trading = _override_trading_fee_mode(settings.trading, fee_mode)
    elif fee_mode == "both":
        logger.info("Fee mode 'both' requested without --scan; using config defaults for live run.")

    if debug_feeds:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        for handler in root_logger.handlers:
            handler.setLevel(logging.DEBUG)
        logging.getLogger("src.strategy.spot_perp_paper").setLevel(logging.DEBUG)
        logging.getLogger("src.hyperliquid_client.client").setLevel(logging.DEBUG)
    if settings.database.backend == "sqlite":
        db_path = settings.database.sqlite_path
        logger.info(
            "SQLite database path resolved to %s (exists=%s)",
            db_path,
            os.path.exists(db_path),
        )

    if settings.validation.enabled:
        logger.info(
            "[VALIDATION] enabled=true sample_interval_ms=%s stats_log_interval_sec=%s sqlite_flush_every_n=%s",
            settings.validation.sample_interval_ms,
            settings.validation.stats_log_interval_sec,
            settings.validation.sqlite_flush_every_n,
        )
    else:
        logger.info("[VALIDATION] enabled=false")

    assets = [a.strip().upper() for a in assets_arg.split(",") if a.strip()] if assets_arg else ["BTC"]
    logger.info("Starting spot-perp paper engine for assets: %s", ", ".join(assets))

    feed_health = FeedHealthTracker(settings.observability.feed_health)
    client = HyperliquidClient(settings.api, settings.network, feed_health_tracker=feed_health)
    session_factory = get_session(settings)
    engine = SpotPerpPaperEngine(
        client,
        assets,
        settings.trading,
        db_session_factory=session_factory,
        feed_health_settings=settings.observability.feed_health,
        feed_health_tracker=feed_health,
        validation_settings=settings.validation,
        would_trade=settings.strategy.would_trade,
        trace_every_seconds=settings.strategy.trace_every_seconds,
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


async def _run_scan(
    config_path: str,
    debug_feeds: bool = False,
    assets_arg: Optional[str] = None,
    top_n: int = 20,
    out_path: str = "/tmp/spotperp_scan.csv",
    fee_mode: str = "both",
    would_trade_override: Optional[bool] = None,
    trace_every_seconds_override: Optional[int] = None,
) -> None:
    settings = load_config(config_path)
    setup_logging(settings.logging)
    init_db(settings)

    if would_trade_override is not None:
        settings.strategy.would_trade = would_trade_override
    if trace_every_seconds_override is not None:
        settings.strategy.trace_every_seconds = trace_every_seconds_override

    if debug_feeds:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        for handler in root_logger.handlers:
            handler.setLevel(logging.DEBUG)
        logging.getLogger("src.strategy.spot_perp_paper").setLevel(logging.DEBUG)
        logging.getLogger("src.hyperliquid_client.client").setLevel(logging.DEBUG)

    assets = _resolve_scan_assets(assets_arg, settings)
    fee_modes = ["maker", "taker"] if fee_mode == "both" else [fee_mode]
    logger.info(
        "Starting spot-perp scan for assets=%s fee_modes=%s window_seconds=%s",
        ", ".join(assets),
        ",".join(fee_modes),
        SCAN_WINDOW_SECONDS,
    )

    metrics_by_asset: dict[str, AssetScanMetrics] = {
        asset: AssetScanMetrics(asset=asset) for asset in assets
    }

    for asset in assets:
        for mode in fee_modes:
            feed_health = FeedHealthTracker(settings.observability.feed_health)
            client = HyperliquidClient(settings.api, settings.network, feed_health_tracker=feed_health)
            session_factory = get_session(settings)
            trading_override = _override_trading_fee_mode(settings.trading, mode)

            def _on_decision(decision: SpotPerpDecision) -> None:
                update_scan_metrics(metrics_by_asset, decision)

            engine = SpotPerpPaperEngine(
                client,
                [asset],
                trading_override,
                db_session_factory=session_factory,
                feed_health_settings=settings.observability.feed_health,
                feed_health_tracker=feed_health,
                validation_settings=settings.validation,
                would_trade=settings.strategy.would_trade,
                trace_every_seconds=settings.strategy.trace_every_seconds,
                decision_callback=_on_decision,
            )
            stop_event = asyncio.Event()
            start_time = time.time()
            try:
                task = asyncio.create_task(engine.run_forever(stop_event=stop_event))
                await asyncio.sleep(SCAN_WINDOW_SECONDS)
                stop_event.set()
                await task
            except KeyboardInterrupt:  # pragma: no cover - manual stop
                logger.info("Keyboard interrupt received, stopping scan early")
                stop_event.set()
            finally:
                await engine.shutdown()
                await client.close()
                elapsed = time.time() - start_time
                logger.info(
                    "[SCAN] asset=%s fee_mode=%s observations=%s elapsed=%.1fs",
                    asset,
                    mode,
                    metrics_by_asset.get(asset, AssetScanMetrics(asset=asset)).observations,
                    elapsed,
                )

    finalized = _finalize_scan_metrics(metrics_by_asset)
    logger.info("Scan complete. Writing CSV to %s", out_path)
    _write_scan_csv(out_path, finalized)
    table = _format_scan_table(finalized, top_n)
    logger.info("[SCAN][TOP_%s]\n%s", top_n, table)


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
    parser.add_argument(
        "--would-trade",
        action="store_true",
        help="Enable would-trade tracing without placing any orders",
    )
    parser.add_argument(
        "--trace-every-seconds",
        type=int,
        default=None,
        help="Minimum seconds between decision trace logs per asset",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Enable scan mode across multiple assets with summary report",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Top N assets to show in scan report",
    )
    parser.add_argument(
        "--out",
        default="/tmp/spotperp_scan.csv",
        help="Path to write scan CSV output",
    )
    parser.add_argument(
        "--fee-mode",
        choices=["maker", "taker", "both"],
        default="both",
        help="Force fee mode for scan estimates (maker, taker, or both)",
    )
    args = parser.parse_args()

    if args.status_only and args.scan:
        raise SystemExit("--status-only cannot be combined with --scan.")

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

    if args.scan:
        try:
            asyncio.run(
                _run_scan(
                    args.config,
                    debug_feeds=args.debug_feeds,
                    assets_arg=args.assets,
                    top_n=args.top,
                    out_path=args.out,
                    fee_mode=args.fee_mode,
                    would_trade_override=args.would_trade,
                    trace_every_seconds_override=args.trace_every_seconds,
                )
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        return

    asyncio.run(
        _run_engine(
            args.config,
            debug_feeds=args.debug_feeds,
            assets_arg=args.assets,
            would_trade_override=args.would_trade,
            trace_every_seconds_override=args.trace_every_seconds,
            fee_mode=args.fee_mode,
        )
    )


if __name__ == "__main__":
    main()
