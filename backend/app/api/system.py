"""系统：总览、模型配置、聊天策略、控制 bot、日志与用量。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as env
from ..core.llm import LLMClient, LLMConfig, load_config
from ..db import get_db
from ..deps import audit, current_user
from ..models import (
    Account, AuditLog, Contact, ControlCommandLog, Message, Setting, UsageLog,
)
from ..schemas import ChatConfigIn, ControlBotIn, LLMConfigIn

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/stats/overview")
async def overview(db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=7)

    accounts = (await db.execute(select(Account))).scalars().all()
    contacts_total = (await db.execute(select(func.count(Contact.id)))).scalar() or 0
    msgs_today = (
        await db.execute(select(func.count(Message.id)).where(Message.created_at >= day_start))
    ).scalar() or 0
    out_today = (
        await db.execute(
            select(func.count(Message.id)).where(Message.created_at >= day_start, Message.direction == "out")
        )
    ).scalar() or 0
    voice_today = (
        await db.execute(
            select(func.count(Message.id)).where(
                Message.created_at >= day_start, Message.msg_type == "voice"
            )
        )
    ).scalar() or 0

    # 7 日趋势
    trend = []
    for i in range(6, -1, -1):
        d0 = day_start - timedelta(days=i)
        d1 = d0 + timedelta(days=1)
        c = (
            await db.execute(
                select(func.count(Message.id)).where(Message.created_at >= d0, Message.created_at < d1)
            )
        ).scalar() or 0
        trend.append({"date": d0.strftime("%m-%d"), "count": c})

    usage = (
        await db.execute(
            select(func.sum(UsageLog.prompt_tokens), func.sum(UsageLog.completion_tokens), func.sum(UsageLog.chars))
            .where(UsageLog.created_at >= week_start)
        )
    ).one()

    recent_audit = (
        await db.execute(select(AuditLog).order_by(desc(AuditLog.id)).limit(8))
    ).scalars().all()

    return {
        "accounts_total": len(accounts),
        "accounts_online": sum(1 for a in accounts if a.status == "online"),
        "accounts_ai_on": sum(1 for a in accounts if a.ai_enabled and a.enabled),
        "contacts_total": contacts_total,
        "messages_today": msgs_today,
        "out_today": out_today,
        "voice_today": voice_today,
        "trend": trend,
        "usage_7d": {
            "prompt_tokens": usage[0] or 0, "completion_tokens": usage[1] or 0, "tts_chars": usage[2] or 0,
        },
        "recent_audit": [
            {"id": a.id, "actor": a.actor, "action": a.action, "created_at": a.created_at.isoformat()}
            for a in recent_audit
        ],
        "llm_configured": bool(env.LLM_BASE_URL or False),
    }


# ---------------- 模型配置 ----------------
@router.get("/settings/llm")
async def get_llm(db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    cfg = await load_config(db)
    return {
        "base_url": cfg.base_url, "model": cfg.model, "json_model": cfg.json_model,
        "temperature": cfg.temperature, "max_tokens": cfg.max_tokens, "timeout": cfg.timeout,
        "api_key_set": bool(cfg.api_key),
        "api_key_mask": ("*" * 8 + cfg.api_key[-4:]) if cfg.api_key else "",
    }


@router.post("/settings/llm")
async def set_llm(body: LLMConfigIn, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    row = await db.get(Setting, "llm_config")
    old = (row.value if row else {}) or {}
    data = body.model_dump()
    if not data.get("api_key"):
        data["api_key"] = old.get("api_key", "")
    if not row:
        row = Setting(key="llm_config", value=data)
        db.add(row)
    else:
        row.value = data
    await audit(db, actor=user["sub"], action="llm_config_updated",
                detail={"base_url": data["base_url"], "model": data["model"]})
    await db.commit()
    return {"ok": True}


@router.post("/settings/llm/test")
async def test_llm(db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    cfg = await load_config(db)
    try:
        client = LLMClient(cfg)
        text, usage = await client.chat(
            [{"role": "user", "content": "只回两个字：在线"}], temperature=0, max_tokens=16
        )
        return {"ok": True, "reply": text[:50], "model": usage.get("model"), "elapsed_ms": usage.get("elapsed_ms")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ---------------- 聊天策略 ----------------
@router.get("/settings/chat")
async def get_chat(db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    from ..tg.handlers import DEFAULT_CHAT_CFG

    row = await db.get(Setting, "chat_config")
    cfg = dict(DEFAULT_CHAT_CFG)
    if row and isinstance(row.value, dict):
        cfg.update(row.value)
    return cfg


@router.post("/settings/chat")
async def set_chat(body: ChatConfigIn, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    row = await db.get(Setting, "chat_config")
    data = body.model_dump()
    if row:
        row.value = data
    else:
        db.add(Setting(key="chat_config", value=data))
    await audit(db, actor=user["sub"], action="chat_config_updated", detail=data)
    await db.commit()
    return {"ok": True}


# ---------------- 控制 bot ----------------
@router.get("/settings/controlbot")
async def get_controlbot(db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    row = await db.get(Setting, "control_bot")
    v = (row.value if row else {}) or {}
    token = v.get("token", "")
    return {
        "token_set": bool(token),
        "token_mask": ("*" * 8 + token[-4:]) if token else "",
        "admin_ids": v.get("admin_ids", []),
    }


@router.post("/settings/controlbot")
async def set_controlbot(body: ControlBotIn, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    row = await db.get(Setting, "control_bot")
    old = (row.value if row else {}) or {}
    data = {"token": body.token or old.get("token", ""), "admin_ids": body.admin_ids}
    if row:
        row.value = data
    else:
        db.add(Setting(key="control_bot", value=data))
    await audit(db, actor=user["sub"], action="controlbot_updated",
                detail={"token_set": bool(data["token"]), "admin_ids": data["admin_ids"]})
    await db.commit()
    return {"ok": True}


# ---------------- 全局接管 ----------------
@router.post("/control/stop_all")
async def stop_all(db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    accounts = (await db.execute(select(Account))).scalars().all()
    for a in accounts:
        a.ai_enabled = False
    await audit(db, actor=user["sub"], action="stop_all", detail={"accounts": len(accounts)})
    await db.commit()
    return {"ok": True, "stopped": len(accounts)}


@router.post("/control/resume_all")
async def resume_all(db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    accounts = (await db.execute(select(Account))).scalars().all()
    for a in accounts:
        a.ai_enabled = True
    await audit(db, actor=user["sub"], action="resume_all", detail={"accounts": len(accounts)})
    await db.commit()
    return {"ok": True, "resumed": len(accounts)}


# ---------------- 日志 ----------------
@router.get("/logs/audit")
async def audit_logs(
    page: int = 1, size: int = 50, action: str = "",
    db: AsyncSession = Depends(get_db), user: dict = Depends(current_user),
):
    q = select(AuditLog).order_by(desc(AuditLog.id))
    if action:
        q = q.where(AuditLog.action.like(f"%{action}%"))
    rows = (await db.execute(q.limit(size).offset((page - 1) * size))).scalars().all()
    total = (await db.execute(select(func.count(AuditLog.id)))).scalar() or 0
    return {
        "total": total,
        "items": [
            {
                "id": a.id, "actor": a.actor, "action": a.action, "object_type": a.object_type,
                "object_id": a.object_id, "detail": a.detail, "ip": a.ip,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ],
    }


@router.get("/logs/usage")
async def usage_logs(
    page: int = 1, size: int = 50, kind: str = "",
    db: AsyncSession = Depends(get_db), user: dict = Depends(current_user),
):
    q = select(UsageLog).order_by(desc(UsageLog.id))
    if kind:
        q = q.where(UsageLog.kind == kind)
    rows = (await db.execute(q.limit(size).offset((page - 1) * size))).scalars().all()
    return [
        {
            "id": u.id, "account_id": u.account_id, "kind": u.kind, "model": u.model,
            "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
            "chars": u.chars, "elapsed_ms": u.elapsed_ms, "ok": u.ok, "error": u.error,
            "created_at": u.created_at.isoformat(),
        }
        for u in rows
    ]


@router.get("/logs/control")
async def control_logs(db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    rows = (await db.execute(select(ControlCommandLog).order_by(desc(ControlCommandLog.id)).limit(50))).scalars().all()
    return [
        {"id": r.id, "source": r.source, "command": r.command, "target": r.target,
         "result": r.result, "created_at": r.created_at.isoformat()}
        for r in rows
    ]
