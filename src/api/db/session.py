"""Engine & session SQLAlchemy."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def normalize_db_url(url: str) -> str:
    """Paksa driver psycopg2 untuk URL PostgreSQL (SQLAlchemy 2.1 default-nya psycopg v3)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_db_url(url)
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool  # satu koneksi bersama untuk in-memory (tes)
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300,
                         connect_args={"connect_timeout": 15, "keepalives": 1, "keepalives_idle": 30,
                                     "keepalives_interval": 10, "keepalives_count": 5})


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
