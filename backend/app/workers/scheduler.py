"""内置调度器：每分钟检查活跃的主动任务，按额度触发（进程内，持有账号客户端）。

RQ 用于纯 CPU/IO 的后台活（风格重建、画像冷启动），不参与实时发消息，
避免跨进程抢同一个 Telegram session。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..db import SessionLocal
from ..models import Account, ProactiveTarget, ProactiveTask
from ..core.typing import in_active_hours

log = logging.getLogger("scheduler")

_running: set[int] = set()
_task: asyncio.Task | None = None


async def _tick() -> None:
    async with SessionLocal() as db:
        tasks = (
            await db.execute(select(ProactiveTask).where(ProactiveTask.status == "active"))
        ).scalars().all()
        due: list[int] = []
        for t in tasks:
            if t.id in _running:
                continue
            acc = await db.get(Account, t.account_id)
            if not acc or not acc.proactive_enabled or not acc.ai_enabled:
                continue
            now = datetime.now(timezone.utc)
            if not in_active_hours(acc.__dict__.get("tz", "UTC") or "UTC", {"start": t.window_start, "end": t.window_end}, now):  # noqa: E501
                # 用账号所属人设时区判断
                from ..models import Persona

                p = await db.get(Persona, acc.persona_id) if acc.persona_id else None
                tz = p.timezone if p else "UTC"
                if not in_active_hours(tz, {"start": t.window_start, "end": t.window_end}, now):
                    continue
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            sent_today = (
                await db.execute(
                    select(func.count(ProactiveTarget.id)).where(
                        ProactiveTarget.task_id == t.id,
                        ProactiveTarget.status == "sent",
                        ProactiveTarget.sent_at >= day_start,
                    )
                )
            ).scalar() or 0
            if sent_today >= t.daily_limit:
                continue
            pending = (
                await db.execute(
                    select(func.count(ProactiveTarget.id)).where(
                        ProactiveTarget.task_id == t.id, ProactiveTarget.status == "pending"
                    )
                )
            ).scalar() or 0
            if pending:
                due.append(t.id)
    for tid in due:
        _running.add(tid)
        asyncio.create_task(_run_one(tid))


async def _run_one(task_id: int) -> None:
    from .workers.jobs import run_proactive_task

    try:
        res = await run_proactive_task(task_id)
        log.info("主动任务 %s 完成: %s", task_id, res)
    except Exception as e:
        log.warning("主动任务 %s 异常: %s", task_id, e)
    finally:
        _running.discard(task_id)


async def _loop() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            await _tick()
        except Exception as e:
            log.warning("调度循环异常: %s", e)
        await asyncio.sleep(60)


def start_scheduler() -> None:
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="proactive-scheduler")


async def stop_scheduler() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except Exception:
            pass
        _task = None
