from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.loader import load_config
from src.config.models import Settings
from src.db.models import Base
from src.db.runtime_status import ensure_runtime_status_row, ensure_status_row

_engine_cache = {}


def build_connection_string(settings: Settings) -> str:
    if settings.database.backend == "sqlite":
        db_path = settings.database.sqlite_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        return f"sqlite:///{db_path}"
    if settings.database.backend == "postgres":
        return (
            f"postgresql+psycopg2://{settings.database.postgres_user}:{settings.database.postgres_password}"
            f"@{settings.database.postgres_host}:{settings.database.postgres_port}/{settings.database.postgres_database}"
        )
    raise ValueError("Unsupported DB backend")


def get_engine(settings: Settings):
    conn = build_connection_string(settings)
    if conn not in _engine_cache:
        _engine_cache[conn] = create_engine(conn, echo=False, future=True)
    return _engine_cache[conn]


def init_db(settings: Settings) -> None:
    engine = get_engine(settings)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    session = Session()
    try:
        ensure_runtime_status_row(session)
        ensure_status_row(session)
    finally:
        session.close()


def get_session(settings: Optional[Settings] = None):
    settings = settings or load_config("config/config.yaml")
    engine = get_engine(settings)
    Session = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def session_scope() -> Iterator:
        session = Session()
        try:
            yield session
        finally:
            session.close()

    session_scope.db_path = (
        settings.database.sqlite_path
        if settings.database.backend == "sqlite"
        else build_connection_string(settings)
    )

    return session_scope
