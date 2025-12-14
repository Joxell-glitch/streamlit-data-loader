from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


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
    whitelist: List[str] = field(default_factory=list)
    blacklist: List[str] = field(default_factory=list)
    min_average_volume: float = 0.0
    max_spread_pct: float = 1.0
    top_n_opportunities: int = 20


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
class Settings:
    network: str
    api: APISettings
    trading: TradingSettings
    database: DatabaseSettings
    logging: LoggingSettings
