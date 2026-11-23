"""三级限速 + 预热期 + FloodWait 精确退避。

计数存 Redis（多进程共享）；Redis 不可用时退回进程内计数（单机轻量模式）。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..config import settings


class _MemoryStore:
    def __init__(self) -> None:
        self._d: dict[str, tuple[int, float]] = {}

    async def incr(self, key: str, ttl: int) -> int:
        val, exp = self._d.get(key, (0, time.time() + ttl))
        if time.time() > exp:
            val, exp = 0, time.time() + ttl
        val += 1
        self._d[key] = (val, exp)
        return val

    async def get(self, key: str) -> str | None:
        val, exp = self._d.get(key, (0, 0))
        if exp and time.time() > exp:
            self._d.pop(key, None)
            return None
        return str(val) if val else None

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._d[key] = (int(value) if value.isdigit() else 0, time.time() + ttl)

    async def delete(self, key: str) -> None:
        self._d.pop(key, None)


_redis = None
_mem = _MemoryStore()


async def _store():
    global _redis
    if settings.QUEUE_BACKEND != "redis":
        return _mem
    if _redis is None:
        try:
            import redis.asyncio as aioredis

            _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await _redis.ping()
        except Exception:
            _redis = False
    return _redis or _mem


class RateLimiter:
    """一账号三维度限速。主动发起比被动回复更保守。"""

    def __init__(self, account) -> None:
        self.account = account
        lim = account.rate_limits or {}
        self.minute = int(lim.get("minute", settings.RL_MINUTE))
        self.hour = int(lim.get("hour", settings.RL_HOUR))
        self.day = int(lim.get("day", settings.RL_DAY))

    # ---------- 预热期 ----------
    def warmup_day(self) -> int:
        if not self.account.warmup_started_at:
            return 0
        started = self.account.warmup_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - started).days)

    def proactive_daily_cap(self) -> int:
        """新号：36h 内 0；第 1 周个位数；之后逐周翻倍到账号日上限。"""
        started = self.account.warmup_started_at
        if not started:
            return 0
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        hours = (datetime.now(timezone.utc) - started).total_seconds() / 3600
        if hours < settings.WARMUP_QUIET_HOURS:
            return 0
        week = int(max(0, hours - settings.WARMUP_QUIET_HOURS) // (24 * 7))
        cap = settings.WARMUP_WEEK1_DAILY * (2**week)
        return min(cap, self.day)

    # ---------- 检查 ----------
    async def check(self, *, proactive: bool = False) -> tuple[bool, str]:
        st = await _store()
        now = datetime.now(timezone.utc)
        fw = await st.get(f"floodwait:{self.account.id}")
        if fw:
            until = float(fw)
            if until > time.time():
                wait = int(until - time.time())
                return False, f"FloodWait 冷却中，还需 {wait} 秒"
        if not self.account.enabled or not self.account.ai_enabled:
            return False, "账号已停用"

        mkey = f"rl:{self.account.id}:m:{now.strftime('%Y%m%d%H%M')}"
        hkey = f"rl:{self.account.id}:h:{now.strftime('%Y%m%d%H')}"
        dkey = f"rl:{self.account.id}:d:{now.strftime('%Y%m%d')}"
        m = int(await st.get(mkey) or 0)
        h = int(await st.get(hkey) or 0)
        d = int(await st.get(dkey) or 0)

        limit_minute = max(1, self.minute // (2 if proactive else 1))
        limit_hour = max(1, self.hour // (3 if proactive else 1))
        limit_day = self.proactive_daily_cap() if proactive else self.day

        if m >= limit_minute:
            return False, f"触发分钟上限（{limit_minute} 条/分钟）"
        if h >= limit_hour:
            return False, f"触发小时上限（{limit_hour} 条/小时）"
        if d >= limit_day:
            return False, f"触发当日上限（{limit_day} 条/天）"
        return True, ""

    async def consume(self, *, proactive: bool = False) -> None:
        st = await _store()
        now = datetime.now(timezone.utc)
        await st.incr(f"rl:{self.account.id}:m:{now.strftime('%Y%m%d%H%M')}", 180)
        await st.incr(f"rl:{self.account.id}:h:{now.strftime('%Y%m%d%H')}", 7200)
        await st.incr(f"rl:{self.account.id}:d:{now.strftime('%Y%m%d')}", 172800)

    async def set_floodwait(self, seconds: int) -> None:
        st = await _store()
        until = int(time.time()) + max(1, seconds)
        await st.setex(f"floodwait:{self.account.id}", max(60, seconds + 30), str(until))

    async def stats(self) -> dict:
        st = await _store()
        now = datetime.now(timezone.utc)
        return {
            "minute": int(await st.get(f"rl:{self.account.id}:m:{now.strftime('%Y%m%d%H%M')}") or 0),
            "hour": int(await st.get(f"rl:{self.account.id}:h:{now.strftime('%Y%m%d%H')}") or 0),
            "day": int(await st.get(f"rl:{self.account.id}:d:{now.strftime('%Y%m%d')}") or 0),
            "limits": {"minute": self.minute, "hour": self.hour, "day": self.day},
            "proactive_cap_today": self.proactive_daily_cap(),
            "warmup_day": self.warmup_day(),
        }
