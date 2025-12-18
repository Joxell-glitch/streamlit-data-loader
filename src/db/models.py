from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, JSON
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class RunMetadata(Base):
    __tablename__ = "run_metadata"
    id = Column(Integer, primary_key=True)
    run_id = Column(String, unique=True, index=True)
    start_timestamp = Column(Float)
    end_timestamp = Column(Float, nullable=True)
    config_snapshot = Column(JSON)
    notes = Column(String, nullable=True)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True)
    run_id = Column(String, index=True)
    timestamp = Column(Float)
    triangle_id = Column(Integer)
    asset_a = Column(String)
    asset_b = Column(String)
    asset_c = Column(String)
    initial_size = Column(Float)
    theoretical_final_amount = Column(Float)
    theoretical_edge = Column(Float)
    estimated_slippage_leg1 = Column(Float)
    estimated_slippage_leg2 = Column(Float)
    estimated_slippage_leg3 = Column(Float)
    parameters_snapshot = Column(JSON)


class TriangularOpportunity(Base):
    __tablename__ = "triangular_opportunities"
    id = Column(Integer, primary_key=True)
    triangle_id = Column(Integer, index=True)
    timestamp = Column(String)
    timestamp_unix = Column(Float, index=True)
    asset_a = Column(String)
    asset_b = Column(String)
    asset_c = Column(String)
    price_leg1 = Column(Float)
    price_leg2 = Column(Float)
    price_leg3 = Column(Float)
    initial_size = Column(Float)
    theoretical_final_amount = Column(Float)
    theoretical_edge = Column(Float)
    profit_absolute = Column(Float)
    profit_percent = Column(Float)


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    id = Column(Integer, primary_key=True)
    run_id = Column(String, index=True)
    timestamp = Column(Float)
    triangle_id = Column(Integer)
    initial_size = Column(Float)
    realized_final_amount = Column(Float)
    realized_pnl = Column(Float)
    realized_edge = Column(Float)
    realized_slippage_leg1 = Column(Float)
    realized_slippage_leg2 = Column(Float)
    realized_slippage_leg3 = Column(Float)
    fees_paid_leg1 = Column(Float)
    fees_paid_leg2 = Column(Float)
    fees_paid_leg3 = Column(Float)
    was_executed = Column(Boolean)
    reason_if_not_executed = Column(String, nullable=True)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    id = Column(Integer, primary_key=True)
    run_id = Column(String, index=True)
    timestamp = Column(Float)
    balances = Column(JSON)
    total_value_in_quote = Column(Float)


class RuntimeStatus(Base):
    __tablename__ = "runtime_status"
    id = Column(Integer, primary_key=True)
    bot_enabled = Column(Boolean, default=True)
    bot_running = Column(Boolean, default=False)
    ws_connected = Column(Boolean, default=False)
    last_heartbeat = Column(Float, nullable=True)


class Status(Base):
    __tablename__ = "status"
    id = Column(Integer, primary_key=True)
    bot_enabled = Column(Boolean, default=True)
    bot_running = Column(Boolean, default=False)
    ws_connected = Column(Boolean, default=False)
    dashboard_connected = Column(Boolean, default=False)
    last_heartbeat = Column(Float, nullable=True)


class ProfitOpportunity(Base):
    __tablename__ = "profit_opportunities"
    id = Column(Integer, primary_key=True)
    triangle_id = Column(Integer, index=True)
    profit = Column(Float)
    timestamp = Column(DateTime)


class SpotPerpOpportunity(Base):
    __tablename__ = "spot_perp_opportunities"
    id = Column(Integer, primary_key=True)
    timestamp = Column(Float)
    asset = Column(String, index=True)
    direction = Column(String)
    spot_price = Column(Float)
    perp_price = Column(Float)
    mark_price = Column(Float)
    spread_gross = Column(Float)
    fee_estimated = Column(Float)
    funding_estimated = Column(Float)
    pnl_net_estimated = Column(Float)


class DecisionSnapshot(Base):
    __tablename__ = "decision_snapshots"
    id = Column(Integer, primary_key=True)
    ts_ms = Column(Integer)
    asset = Column(String, index=True)
    spot_bid = Column(Float)
    spot_ask = Column(Float)
    perp_bid = Column(Float)
    perp_ask = Column(Float)
    spot_age_ms = Column(Float, nullable=True)
    perp_age_ms = Column(Float, nullable=True)
    spot_incomplete = Column(Integer)
    perp_incomplete = Column(Integer)
    stale = Column(Integer)
    crossed = Column(Integer)
    out_of_sync = Column(Integer)


class DecisionOutcome(Base):
    __tablename__ = "decision_outcomes"
    id = Column(Integer, primary_key=True)
    ts_ms = Column(Integer)
    asset = Column(String, index=True)
    outcome = Column(String)
    reason = Column(String)
    detail = Column(String, nullable=True)
