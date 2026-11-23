"""时间工具：统一 UTC，兼容 SQLite（读回来的 datetime 不带时区）。"""
from __future__ import annotations

from datetime import datetime, timezone


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def is_past(dt: datetime | None, now: datetime | None = None) -> bool:
    d = as_utc(dt)
    if not d:
        return True
    return d < (now or datetime.now(timezone.utc))
