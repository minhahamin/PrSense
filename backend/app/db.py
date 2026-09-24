"""Async DB engine/session. Postgres on Railway, SQLite fallback for local dev.

- `DATABASE_URL` set (Railway injects it when Postgres plugin is added):
  `postgres://` / `postgresql://` → `postgresql+asyncpg://`
- unset → SQLite file at `$SQLITE_PATH`, `/data/prsense.db` (volume), or `./prsense.db`.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def resolve_database_url(raw: str, sqlite_path: str = "") -> str:
    raw = (raw or "").strip()
    if raw:
        if raw.startswith("postgres://"):
            return "postgresql+asyncpg://" + raw[len("postgres://") :]
        if raw.startswith("postgresql://") and "+asyncpg" not in raw:
            return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
        return raw
    # SQLite fallback
    import os

    if sqlite_path:
        path = sqlite_path
    elif os.path.isdir("/data"):
        path = "/data/prsense.db"
    else:
        path = "./prsense.db"
    return f"sqlite+aiosqlite:///{path}"


@lru_cache
def _engine():
    from app.config import get_settings

    s = get_settings()
    url = resolve_database_url(s.database_url, s.sqlite_path)
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, pool_pre_ping=True, **kwargs)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), class_=AsyncSession, expire_on_commit=False)


def database_dialect() -> str:
    return _engine().url.get_backend_name()


async def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    async with _engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def reset_engine_cache() -> None:
    _engine.cache_clear()
