from __future__ import annotations

import os
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

from .models import (
    APISettings,
    DatabaseSettings,
    FeedHealthSettings,
    LoggingSettings,
    ObservabilitySettings,
    Settings,
    StrategySettings,
    TradingSettings,
    ValidationSettings,
)

ENV_PREFIX = ""


def load_config(config_path: str) -> Settings:
    """Load configuration from YAML and environment variables."""
    load_dotenv()
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    raw = apply_env_overrides(raw)

    api = APISettings(
        rest_base=raw["api"]["rest_base"],
        info_path=raw["api"].get("info_path", "/info"),
        websocket_url=raw["api"]["websocket_url"],
        testnet_rest_base=raw["api"].get("testnet_rest_base", raw["api"]["rest_base"]),
        testnet_websocket_url=raw["api"].get("testnet_websocket_url", raw["api"]["websocket_url"]),
    )

    trading = TradingSettings(**raw["trading"])

    db = DatabaseSettings(
        backend=raw["database"]["backend"],
        sqlite_path=raw["database"].get("sqlite_path", "data/arb_bot.sqlite"),
        postgres_host=raw["database"].get("postgres", {}).get("host"),
        postgres_port=raw["database"].get("postgres", {}).get("port"),
        postgres_user=raw["database"].get("postgres", {}).get("user"),
        postgres_password=raw["database"].get("postgres", {}).get("password"),
        postgres_database=raw["database"].get("postgres", {}).get("database"),
    )

    logging = LoggingSettings(**raw["logging"])

    obs_raw = raw.get("observability", {})
    feed_health_raw = raw.get("feed_health", obs_raw.get("feed_health", {})) or {}
    observability = ObservabilitySettings(
        log_top_n_each_sec=obs_raw.get("log_top_n_each_sec", 60),
        top_n=obs_raw.get("top_n", 10),
        min_abs_profit_to_log=obs_raw.get("min_abs_profit_to_log", 0.0),
        feed_health=FeedHealthSettings(**feed_health_raw),
    )

    validation_raw = raw.get("validation", {}) or {}
    raw_enabled = validation_raw.get("enabled", False)
    parsed_enabled = (
        str(raw_enabled).lower() in {"1", "true", "yes", "on"}
        if isinstance(raw_enabled, str)
        else bool(raw_enabled)
    )

    validation = ValidationSettings(
        enabled=parsed_enabled,
        sample_interval_ms=int(validation_raw.get("sample_interval_ms", 250)),
        stats_log_interval_sec=int(validation_raw.get("stats_log_interval_sec", 5)),
        sqlite_flush_every_n=int(validation_raw.get("sqlite_flush_every_n", 50)),
    )

    strategy_raw = raw.get("strategy", {}) or {}
    strategy = StrategySettings(
        would_trade=str(strategy_raw.get("would_trade", False)).lower() in {"1", "true", "yes", "on"},
        trace_every_seconds=int(strategy_raw.get("trace_every_seconds", 10)),
    )

    return Settings(
        network=raw["network"],
        api=api,
        trading=trading,
        database=db,
        logging=logging,
        observability=observability,
        strategy=strategy,
        validation=validation,
    )


def apply_env_overrides(raw: Dict[str, Any]) -> Dict[str, Any]:
    env = os.environ
    raw["network"] = env.get("NETWORK", raw.get("network", "mainnet"))

    raw.setdefault("trading", {})
    raw["trading"].setdefault("spot_pair_overrides", {})
    raw["trading"].setdefault("spot_fee_mode", "maker")
    raw["trading"].setdefault("perp_fee_mode", "maker")
    raw["trading"].setdefault("maker_fee_spot", 0.0)
    raw["trading"].setdefault("maker_fee_perp", 0.0)
    raw["trading"].setdefault("taker_fee_spot", raw["trading"].get("taker_fee_spot", 0.001))
    raw["trading"].setdefault("taker_fee_perp", raw["trading"].get("taker_fee_perp", 0.0005))
    raw["trading"]["max_assets_per_ws"] = int(
        env.get("TRADING_MAX_ASSETS_PER_WS", raw["trading"].get("max_assets_per_ws", 50))
    )

    raw.setdefault("api", {})
    raw["api"]["rest_base"] = env.get("REST_BASE", raw["api"].get("rest_base"))
    raw["api"]["info_path"] = env.get("INFO_PATH", raw["api"].get("info_path", "/info"))
    raw["api"]["websocket_url"] = env.get("WEBSOCKET_URL", raw["api"].get("websocket_url"))
    raw["api"]["testnet_rest_base"] = env.get("TESTNET_REST_BASE", raw["api"].get("testnet_rest_base", raw["api"].get("rest_base")))
    raw["api"]["testnet_websocket_url"] = env.get("TESTNET_WEBSOCKET_URL", raw["api"].get("testnet_websocket_url", raw["api"].get("websocket_url")))

    raw.setdefault("database", {})
    raw["database"]["backend"] = env.get("DB_BACKEND", raw["database"].get("backend", "sqlite"))
    raw["database"]["sqlite_path"] = env.get("SQLITE_PATH", raw["database"].get("sqlite_path", "data/arb_bot.sqlite"))
    raw.setdefault("database", {}).setdefault("postgres", {})
    pg = raw["database"]["postgres"]
    pg["host"] = env.get("POSTGRES_HOST", pg.get("host"))
    pg["port"] = int(env.get("POSTGRES_PORT", pg.get("port", 5432)))
    pg["user"] = env.get("POSTGRES_USER", pg.get("user"))
    pg["password"] = env.get("POSTGRES_PASSWORD", pg.get("password"))
    pg["database"] = env.get("POSTGRES_DATABASE", pg.get("database"))

    raw.setdefault("logging", {})
    raw["logging"]["level"] = env.get("LOG_LEVEL", raw["logging"].get("level", "INFO"))
    raw["logging"]["log_file"] = env.get("LOG_FILE", raw["logging"].get("log_file", "data/bot.log"))
    raw["logging"]["console"] = str(env.get("LOG_CONSOLE", raw["logging"].get("console", "true"))).lower() in {"1", "true", "yes", "on"}

    raw.setdefault("observability", {})
    raw["observability"]["log_top_n_each_sec"] = int(
        env.get("OBS_LOG_TOP_N_EACH_SEC", raw["observability"].get("log_top_n_each_sec", 60))
    )
    raw["observability"]["top_n"] = int(env.get("OBS_TOP_N", raw["observability"].get("top_n", 10)))
    raw["observability"]["min_abs_profit_to_log"] = float(
        env.get("OBS_MIN_ABS_PROFIT_TO_LOG", raw["observability"].get("min_abs_profit_to_log", 0.0))
    )

    raw.setdefault("feed_health", {})
    raw["feed_health"]["log_interval_sec"] = float(
        env.get("FEED_HEALTH_LOG_INTERVAL_SEC", raw["feed_health"].get("log_interval_sec", 1))
    )
    raw["feed_health"]["stale_ms"] = int(env.get("FEED_HEALTH_STALE_MS", raw["feed_health"].get("stale_ms", 1500)))
    raw["feed_health"]["out_of_sync_ms"] = int(
        env.get("FEED_HEALTH_OUT_OF_SYNC_MS", raw["feed_health"].get("out_of_sync_ms", 1000))
    )
    raw["feed_health"]["dedup_ttl_sec"] = int(
        env.get("FEED_HEALTH_DEDUP_TTL_SEC", raw["feed_health"].get("dedup_ttl_sec", 2))
    )

    raw.setdefault("validation", {})
    raw["validation"]["enabled"] = env.get("VALIDATION_ENABLED", raw["validation"].get("enabled", False))
    raw["validation"]["sample_interval_ms"] = int(
        env.get("VALIDATION_SAMPLE_INTERVAL_MS", raw["validation"].get("sample_interval_ms", 250))
    )
    raw["validation"]["stats_log_interval_sec"] = int(
        env.get("VALIDATION_STATS_LOG_INTERVAL_SEC", raw["validation"].get("stats_log_interval_sec", 5))
    )
    raw["validation"]["sqlite_flush_every_n"] = int(
        env.get("VALIDATION_SQLITE_FLUSH_EVERY_N", raw["validation"].get("sqlite_flush_every_n", 50))
    )

    raw.setdefault("strategy", {})
    raw["strategy"]["would_trade"] = env.get("STRATEGY_WOULD_TRADE", raw["strategy"].get("would_trade", False))
    raw["strategy"]["trace_every_seconds"] = int(
        env.get("STRATEGY_TRACE_EVERY_SECONDS", raw["strategy"].get("trace_every_seconds", 10))
    )

    return raw
