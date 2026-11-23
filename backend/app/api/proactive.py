"""主动会话任务：选人、目标、时段、频率、开场白、错峰。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import audit, current_user
from ..models import Account, Contact, ProactiveTarget, ProactiveTask
from ..schemas import ProactiveTaskIn

router = APIRouter(prefix="/api/proactive", tags=["proactive"])


def ser(t: ProactiveTask) -> dict:
    return {
        "id": t.id, "account_id": t.account_id, "name": t.name, "goal": t.goal,
        "persona_id": t.persona_id, "filters": t.filters,
        "window_start": t.window_start, "window_end": t.window_end,
        "daily_limit": t.daily_limit, "interval_min": t.interval_min, "interval_max": t.interval_max,
        "status": t.status, "created_count": t.created_count,
        "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/tasks")
async def list_tasks(account_id: int | None = None, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    q = select(ProactiveTask).order_by(desc(ProactiveTask.id))
    if account_id:
        q = q.where(ProactiveTask.account_id == account_id)
    rows = (await db.execute(q)).scalars().all()
    out = []
    for t in rows:
        targets = (
            await db.execute(select(ProactiveTarget).where(ProactiveTarget.task_id == t.id))
        ).scalars().all()
        counts = {
            "pending": sum(1 for x in targets if x.status == "pending"),
            "sent": sum(1 for x in targets if x.status == "sent"),
            "failed": sum(1 for x in targets if x.status == "failed"),
            "replied": sum(1 for x in targets if x.status == "replied"),
        }
        out.append(ser(t) | {"counts": counts})
    return out


@router.post("/tasks")
async def create_task(body: ProactiveTaskIn, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    acc = await db.get(Account, body.account_id)
    if not acc:
        raise HTTPException(404, "账号不存在")
    t = ProactiveTask(**body.model_dump())
    db.add(t)
    await db.flush()
    await audit(db, actor=user["sub"], action="proactive_created", object_type="task", object_id=t.id,
                detail={"name": t.name})
    await db.commit()
    return ser(t)


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: int, body: ProactiveTaskIn, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)
):
    t = await db.get(ProactiveTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    await audit(db, actor=user["sub"], action="proactive_updated", object_type="task", object_id=task_id)
    await db.commit()
    return ser(t)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    t = await db.get(ProactiveTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    await db.delete(t)
    await audit(db, actor=user["sub"], action="proactive_deleted", object_type="task", object_id=task_id)
    await db.commit()
    return {"ok": True}


@router.get("/tasks/{task_id}/targets")
async def list_targets(task_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    rows = (
        await db.execute(
            select(ProactiveTarget).where(ProactiveTarget.task_id == task_id).order_by(desc(ProactiveTarget.id)).limit(200)
        )
    ).scalars().all()
    out = []
    for r in rows:
        c = await db.get(Contact, r.contact_id)
        out.append({
            "id": r.id, "contact_id": r.contact_id,
            "name": (c.first_name if c else "") or (c.username if c else ""),
            "username": c.username if c else "",
            "status": r.status, "opening": r.opening, "error": r.error,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        })
    return out


@router.post("/tasks/{task_id}/preview")
async def preview_targets(
    task_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)
):
    """按筛选条件（标签 / 最后互动天数 / 数量上限）返回候选。"""
    t = await db.get(ProactiveTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    f = t.filters or {}
    days = int(f.get("last_active_days", 0) or 0)
    limit = int(f.get("limit", 50) or 50)
    tags = f.get("tags") or []
    stmt = select(Contact).where(Contact.account_id == t.account_id, Contact.blacklist == False)  # noqa: E712
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = stmt.where((Contact.last_msg_at == None) | (Contact.last_msg_at >= cutoff))  # noqa: E711
    rows = (await db.execute(stmt.order_by(desc(Contact.last_msg_at)).limit(500))).scalars().all()
    if tags:
        rows = [c for c in rows if set(tags) & set(c.tags or [])]
    existing = {
        r[0] for r in (await db.execute(select(ProactiveTarget.contact_id).where(ProactiveTarget.task_id == t.id))).all()
    }
    items = [
        {
            "contact_id": c.id, "name": c.first_name or c.username or str(c.tg_id),
            "username": c.username, "last_msg_at": c.last_msg_at.isoformat() if c.last_msg_at else None,
            "already_in_task": c.id in existing,
        }
        for c in rows[:limit]
    ]
    return {"count": len(items), "items": items}


@router.post("/tasks/{task_id}/build")
async def build_targets(
    task_id: int,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user),
):
    """把候选写进任务队列（跳过已存在的，避免重复找人）。"""
    t = await db.get(ProactiveTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    ids = (body or {}).get("contact_ids")
    if not ids:
        prev = await preview_targets(task_id, db=db, user=user)
        ids = [x["contact_id"] for x in prev["items"] if not x["already_in_task"]]
    existing = {
        r[0] for r in (await db.execute(select(ProactiveTarget.contact_id).where(ProactiveTarget.task_id == t.id))).all()
    }
    added = 0
    for cid in ids:
        if cid in existing:
            continue
        if not await db.get(Contact, cid):
            continue
        db.add(ProactiveTarget(task_id=task_id, contact_id=cid, status="pending"))
        added += 1
    await audit(db, actor=user["sub"], action="proactive_build", object_type="task", object_id=task_id,
                detail={"added": added})
    await db.commit()
    return {"added": added}


@router.post("/tasks/{task_id}/start")
async def start_task(task_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    t = await db.get(ProactiveTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    t.status = "active"
    await audit(db, actor=user["sub"], action="proactive_started", object_type="task", object_id=task_id)
    await db.commit()
    return {"ok": True}


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    t = await db.get(ProactiveTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    t.status = "paused"
    await audit(db, actor=user["sub"], action="proactive_paused", object_type="task", object_id=task_id)
    await db.commit()
    return {"ok": True}


@router.post("/tasks/{task_id}/run_once")
async def run_once(task_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    """立即执行一次（后台跑，不阻塞接口）。"""
    from ..workers.jobs import run_proactive_task

    await audit(db, actor=user["sub"], action="proactive_run_once", object_type="task", object_id=task_id)
    await db.commit()
    asyncio.create_task(run_proactive_task(task_id, max_sends=1))
    return {"ok": True, "msg": "已在后台执行一条，稍后看任务日志"}
