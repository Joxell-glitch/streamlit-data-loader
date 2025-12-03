from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class RunMetadata(Base):
    __tablename__ = "run_metadata"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    start_timestamp: Mapped[float] = mapped_column(Float)
    end_timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)
    config_snapshot: Mapped[dict] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    triangle_id: Mapped[int] = mapped_column(Integer)
    asset_a: Mapped[str] = mapped_column(String)
    asset_b: Mapped[str] = mapped_column(String)
    asset_c: Mapped[str] = mapped_column(String)
    initial_size: Mapped[float] = mapped_column(Float)
    theoretical_final_amount: Mapped[float] = mapped_column(Float)
    theoretical_edge: Mapped[float] = mapped_column(Float)
    estimated_slippage_leg1: Mapped[float] = mapped_column(Float)
    estimated_slippage_leg2: Mapped[float] = mapped_column(Float)
    estimated_slippage_leg3: Mapped[float] = mapped_column(Float)
    parameters_snapshot: Mapped[dict] = mapped_column(JSON)


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    triangle_id: Mapped[int] = mapped_column(Integer)
    initial_size: Mapped[float] = mapped_column(Float)
    realized_final_amount: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float)
    realized_edge: Mapped[float] = mapped_column(Float)
    realized_slippage_leg1: Mapped[float] = mapped_column(Float)
    realized_slippage_leg2: Mapped[float] = mapped_column(Float)
    realized_slippage_leg3: Mapped[float] = mapped_column(Float)
    fees_paid_leg1: Mapped[float] = mapped_column(Float)
    fees_paid_leg2: Mapped[float] = mapped_column(Float)
    fees_paid_leg3: Mapped[float] = mapped_column(Float)
    was_executed: Mapped[bool] = mapped_column(Boolean)
    reason_if_not_executed: Mapped[str | None] = mapped_column(String, nullable=True)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    balances: Mapped[dict] = mapped_column(JSON)
    total_value_in_quote: Mapped[float] = mapped_column(Float)
