import os
import time
from typing import List, Optional

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import case, create_engine, func
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, PaperTrade, RunMetadata, Status
from src.db.runtime_status import ensure_runtime_status_row, ensure_status_row, update_runtime_status

DB_PATH = os.getenv("DB_PATH", "data/arb_bot.sqlite")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "data/bot.log")

engine = create_engine(f"sqlite:///{DB_PATH}")
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

Base.metadata.create_all(engine)
with SessionLocal() as session:
    ensure_runtime_status_row(session)
    ensure_status_row(session)

app = FastAPI(title="Hyperliquid Arbitrage Bot API", openapi_url="/api/openapi.json")

origins_env = os.getenv("ALLOWED_ORIGINS", "*")
if origins_env == "*":
    # Permette tutti gli origin in sviluppo; configurare ALLOWED_ORIGINS in produzione.
    allowed_origins = ["*"]
else:
    allowed_origins = [o.strip() for o in origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class StatusResponse(BaseModel):
    bot_running: bool
    websocket_connected: bool
    dashboard_connected: bool
    last_heartbeat: Optional[float]
    bot_enabled: bool


class RunResponse(BaseModel):
    id: int
    run_id: str
    start_timestamp: Optional[float]
    end_timestamp: Optional[float]
    total_trades: int
    total_pnl: float
    win_rate: float
    status: str


class TradeResponse(BaseModel):
    id: int
    run_id: str
    pair_path: Optional[str]
    entry_price: Optional[float]
    exit_price: Optional[float]
    size: Optional[float]
    pnl: Optional[float]
    timestamp: Optional[float]


class LogsResponse(BaseModel):
    lines: List[str]


@app.get("/api/status", response_model=StatusResponse)
def api_status(db: Session = Depends(get_db)):
    status = ensure_status_row(db)
    status.dashboard_connected = True
    db.commit()
    db.refresh(status)
    return {
        "bot_running": bool(status.bot_running),
        "websocket_connected": bool(status.ws_connected),
        "dashboard_connected": bool(status.dashboard_connected),
        "last_heartbeat": status.last_heartbeat,
        "bot_enabled": bool(status.bot_enabled),
    }


@app.post("/api/start", response_model=StatusResponse)
def start_bot(db: Session = Depends(get_db)):
    status = update_runtime_status(db, bot_enabled=True)
    status.dashboard_connected = True
    db.commit()
    db.refresh(status)
    return {
        "bot_running": bool(status.bot_running),
        "websocket_connected": bool(status.ws_connected),
        "dashboard_connected": bool(status.dashboard_connected),
        "last_heartbeat": status.last_heartbeat,
        "bot_enabled": bool(status.bot_enabled),
    }


@app.post("/api/stop", response_model=StatusResponse)
def stop_bot(db: Session = Depends(get_db)):
    status = update_runtime_status(db, bot_enabled=False, bot_running=False, ws_connected=False)
    status.dashboard_connected = True
    db.commit()
    db.refresh(status)
    return {
        "bot_running": bool(status.bot_running),
        "websocket_connected": bool(status.ws_connected),
        "dashboard_connected": bool(status.dashboard_connected),
        "last_heartbeat": status.last_heartbeat,
        "bot_enabled": bool(status.bot_enabled),
    }


@app.get("/api/runs", response_model=List[RunResponse])
def get_runs(db: Session = Depends(get_db)):
    results = (
        db.query(
            RunMetadata,
            func.count(PaperTrade.id).label("total_trades"),
            func.coalesce(func.sum(PaperTrade.realized_pnl), 0).label("total_pnl"),
            func.sum(
                case((PaperTrade.realized_pnl > 0, 1), else_=0)
            ).label("win_count"),
        )
        .outerjoin(PaperTrade, RunMetadata.run_id == PaperTrade.run_id)
        .group_by(RunMetadata.id)
        .order_by(RunMetadata.start_timestamp.desc())
        .all()
    )

    payload: List[RunResponse] = []
    for meta, total_trades, total_pnl, win_count in results:
        win_rate = (win_count or 0) / total_trades if total_trades else 0
        status = "completed" if meta.end_timestamp else "running"
        payload.append(
            RunResponse(
                id=meta.id,
                run_id=meta.run_id,
                start_timestamp=meta.start_timestamp,
                end_timestamp=meta.end_timestamp,
                total_trades=total_trades or 0,
                total_pnl=float(total_pnl or 0),
                win_rate=float(win_rate),
                status=status,
            )
        )
    return payload


@app.get("/api/trades", response_model=List[TradeResponse])
def get_trades(run_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    query = db.query(PaperTrade)
    if run_id:
        query = query.filter(PaperTrade.run_id == run_id)
    trades = query.order_by(PaperTrade.timestamp.desc()).all()
    payload: List[TradeResponse] = []
    for trade in trades:
        pair_path = getattr(trade, "pair_path", None)
        entry_price = getattr(trade, "entry_price", None)
        exit_price = getattr(trade, "exit_price", None)
        size = getattr(trade, "size", None) or trade.initial_size
        pnl = getattr(trade, "pnl", None) or trade.realized_pnl
        payload.append(
            TradeResponse(
                id=trade.id,
                run_id=trade.run_id,
                pair_path=pair_path,
                entry_price=entry_price,
                exit_price=exit_price,
                size=size,
                pnl=pnl,
                timestamp=trade.timestamp,
            )
        )
    return payload


@app.get("/api/logs", response_model=LogsResponse)
def get_logs():
    if not os.path.exists(LOG_FILE_PATH):
        return LogsResponse(lines=[])

    with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    recent = lines[-500:]
    return LogsResponse(lines=[line.rstrip("\n") for line in recent])


@app.get("/api/status/ping", response_model=StatusResponse)
def dashboard_ping(db: Session = Depends(get_db)):
    status = ensure_status_row(db)
    status.dashboard_connected = True
    status.last_heartbeat = status.last_heartbeat or time.time()
    db.commit()
    db.refresh(status)
    return {
        "bot_running": bool(status.bot_running),
        "websocket_connected": bool(status.ws_connected),
        "dashboard_connected": bool(status.dashboard_connected),
        "last_heartbeat": status.last_heartbeat,
        "bot_enabled": bool(status.bot_enabled),
    }
