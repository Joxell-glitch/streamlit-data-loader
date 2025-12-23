from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class APISettings:
    rest_base: str
    info_path: str
    websocket_url: str
    testnet_rest_base: str
    testnet_websocket_url: str


@dataclass
class TradingSettings:
    quote_asset: str
    initial_quote_balance: float
    min_position_size: float
    max_position_size: float
    min_edge_threshold: float
    safety_slippage_buffer: float
    max_concurrent_triangles: int
    fee_mode: str = "maker"
    spot_fee_mode: str = "maker"
    perp_fee_mode: str = "maker"
    maker_fee_spot: float = 0.0
    maker_fee_perp: float = 0.0
    taker_fee_spot: float = 0.001
    taker_fee_perp: float = 0.0005
    whitelist: List[str] = field(default_factory=list)
    blacklist: List[str] = field(default_factory=list)
    spot_pair_overrides: Dict[str, str] = field(default_factory=dict)
    min_average_volume: float = 0.0
    max_spread_pct: float = 1.0
    top_n_opportunities: int = 20
    max_assets_per_ws: int = 50
    universe_assets: List[str] = field(default_factory=list)


@dataclass
class DatabaseSettings:
    backend: str
    sqlite_path: str
    postgres_host: Optional[str] = None
    postgres_port: Optional[int] = None
    postgres_user: Optional[str] = None
    postgres_password: Optional[str] = None
    postgres_database: Optional[str] = None


@dataclass
class LoggingSettings:
    level: str
    log_file: str
    console: bool = True


@dataclass
class FeedHealthSettings:
    log_interval_sec: float = 1.0
    stale_ms: int = 1500
    out_of_sync_ms: int = 1000
    dedup_ttl_sec: int = 2


@dataclass
class ObservabilitySettings:
    log_top_n_each_sec: int = 60
    top_n: int = 10
    min_abs_profit_to_log: float = 0.0
    feed_health: FeedHealthSettings = field(default_factory=FeedHealthSettings)


@dataclass
class ValidationSettings:
    enabled: bool = False
    sample_interval_ms: int = 250
    stats_log_interval_sec: int = 5
    sqlite_flush_every_n: int = 50


@dataclass
class StrategySettings:
    would_trade: bool = False
    trace_every_seconds: int = 10


@dataclass
class Settings:
    network: str
    api: APISettings
    trading: TradingSettings
    database: DatabaseSettings
    logging: LoggingSettings
    observability: ObservabilitySettings
    strategy: StrategySettings = field(default_factory=StrategySettings)
    validation: ValidationSettings = field(default_factory=ValidationSettings)
