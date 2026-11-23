"""异步数据库会话。生产用 PostgreSQL，轻量模式可用 SQLite（同一套模型）。"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}


engine = create_async_engine(settings.DATABASE_URL, echo=False, **_engine_kwargs(settings.DATABASE_URL))
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from . import models  # noqa: F401  注册所有表

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
