"""会话：列表、实时对话流、手动插话、一键停、清记忆。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import audit, current_user
from ..core.timeutil import as_utc
from ..models import Account, Contact, Message
from ..schemas import ManualMessage
from ..tg.manager import human_send, manager

router = APIRouter(prefix="/api/chats", tags=["chats"])


def ser_msg(m: Message) -> dict:
    return {
        "id": m.id, "direction": m.direction, "source": m.source, "text": m.text,
        "lang": m.lang, "msg_type": m.msg_type, "meta": m.meta or {},
        "tg_msg_id": m.tg_msg_id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("")
async def list_chats(
    account_id: int | None = None,
    q: str = "",
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user),
):
    stmt = select(Contact)
    if account_id:
        stmt = stmt.where(Contact.account_id == account_id)
    contacts = (await db.execute(stmt.order_by(desc(Contact.last_msg_at)).limit(300))).scalars().all()
    out = []
    for c in contacts:
        last = (
            await db.execute(
                select(Message).where(Message.contact_id == c.id).order_by(desc(Message.created_at)).limit(1)
            )
        ).scalar_one_or_none()
        if not last:
            continue
        if q and q.lower() not in (c.first_name or "").lower() and q.lower() not in (c.username or "").lower():
            continue
        acc = await db.get(Account, c.account_id)
        ai_on = c.ai_enabled and not c.blacklist and not (
            c.mute_until and as_utc(c.mute_until) > datetime.now(timezone.utc)
        )
        out.append({
            "contact_id": c.id, "account_id": c.account_id,
            "account": acc.label if acc else "", "name": c.first_name or c.username or str(c.tg_id),
            "username": c.username, "lang": c.lang, "intimacy": c.intimacy,
            "last_message": last.text[:80], "last_direction": last.direction,
            "last_time": last.created_at.isoformat(), "ai_active": bool(ai_on),
            "mute_until": c.mute_until.isoformat() if c.mute_until else None,
            "blacklist": c.blacklist,
        })
    start = (page - 1) * size
    return {"total": len(out), "items": out[start : start + size]}


@router.get("/{contact_id}/messages")
async def get_messages(
    contact_id: int,
    before_id: int | None = None,
    limit: int = 40,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user),
):
    stmt = select(Message).where(Message.contact_id == contact_id)
    if before_id:
        stmt = stmt.where(Message.id < before_id)
    rows = (
        await db.execute(stmt.order_by(desc(Message.id)).limit(min(limit, 100)))
    ).scalars().all()
    return [ser_msg(m) for m in reversed(rows)]


@router.post("/{contact_id}/send")
async def manual_send(
    contact_id: int,
    body: ManualMessage,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user),
):
    """人工插话：直接发出，并把这条计入上下文。"""
    c = await db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    runner = manager.runners.get(c.account_id)
    if not runner or not runner.client:
        raise HTTPException(400, "账号未在线，先启动账号")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "内容不能为空")

    from ..core.typing import plan_send

    plan = plan_send(text, persona_paragraph="整条", is_stranger=False, voice_ratio=0)
    plan.read_delay = 0
    ids = await human_send(account_id=c.account_id, tg_id=c.tg_id, text=text, plan=plan)

    from ..tg.handlers import _mark_ai_sent

    for mid in ids:
        _mark_ai_sent(c.account_id, mid)
    m = Message(
        account_id=c.account_id, contact_id=contact_id, direction="out", source="manual",
        text=text, tg_msg_id=ids[0] if ids else None, meta={"by": user["sub"]},
    )
    db.add(m)
    await audit(db, actor=user["sub"], action="manual_send", object_type="contact", object_id=contact_id)
    await db.commit()
    return ser_msg(m)


@router.post("/{contact_id}/stop")
async def stop_chat(contact_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    c = await db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    c.ai_enabled = False
    c.mute_until = None
    await audit(db, actor=user["sub"], action="chat_stopped", object_type="contact", object_id=contact_id)
    await db.commit()
    return {"ok": True, "ai_active": False}


@router.post("/{contact_id}/resume")
async def resume_chat(contact_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    c = await db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    c.ai_enabled = True
    c.mute_until = None
    await audit(db, actor=user["sub"], action="chat_resumed", object_type="contact", object_id=contact_id)
    await db.commit()
    return {"ok": True, "ai_active": True}


@router.delete("/{contact_id}/memory")
async def clear_memory(contact_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    """清空这个联系人的记忆与对话记录（高危，前端二次确认）。"""
    from ..core.memory import clear_contact_memory

    n = await clear_contact_memory(db, 0, contact_id)
    await audit(db, actor=user["sub"], action="memory_cleared", object_type="contact", object_id=contact_id,
                detail={"facts_deleted": n})
    await db.commit()
    return {"ok": True, "deleted": n}
