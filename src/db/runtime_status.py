from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import RuntimeStatus


DEFAULT_STATUS = {
    "id": 1,
    "bot_enabled": True,
    "bot_running": False,
    "ws_connected": False,
    "last_heartbeat": None,
}


def ensure_runtime_status_row(session: Session) -> RuntimeStatus:
    status = session.query(RuntimeStatus).filter_by(id=1).first()
    if not status:
        status = RuntimeStatus(**DEFAULT_STATUS)
        session.add(status)
        session.commit()
        session.refresh(status)
    return status


def get_runtime_status(session: Session) -> RuntimeStatus:
    return ensure_runtime_status_row(session)


def update_runtime_status(session: Session, **fields: Any) -> RuntimeStatus:
    status = ensure_runtime_status_row(session)
    for key, value in fields.items():
        if hasattr(status, key):
            setattr(status, key, value)
    if "last_heartbeat" not in fields:
        status.last_heartbeat = status.last_heartbeat or time.time()
    session.commit()
    session.refresh(status)
    return status
