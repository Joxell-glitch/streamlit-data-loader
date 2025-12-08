from sqlalchemy import Boolean, Column, Float, Integer, String, JSON
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
