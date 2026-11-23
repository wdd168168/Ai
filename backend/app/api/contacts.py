"""联系人 / 会话对象：列表、画像、记忆事实、黑白名单开关。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import audit, current_user
from ..models import Account, Contact, MemoryFact, Message
from ..schemas import ContactUpdate
from ..workers.jobs import cold_start_job

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


def ser(c: Contact, extra: dict | None = None) -> dict:
    return {
        "id": c.id, "account_id": c.account_id, "tg_id": c.tg_id, "username": c.username,
        "name": " ".join(filter(None, [c.first_name, c.last_name])),
        "first_name": c.first_name, "last_name": c.last_name, "lang": c.lang, "tags": c.tags,
        "note": c.note, "blacklist": c.blacklist, "ai_enabled": c.ai_enabled,
        "mute_until": c.mute_until.isoformat() if c.mute_until else None,
        "intimacy": c.intimacy, "interests": c.interests, "avoid_topics": c.avoid_topics,
        "emotion_baseline": c.emotion_baseline, "unfinished_topics": c.unfinished_topics,
        "key_facts": c.key_facts,
        "profile_updated_at": c.profile_updated_at.isoformat() if c.profile_updated_at else None,
        "last_msg_at": c.last_msg_at.isoformat() if c.last_msg_at else None,
        **(extra or {}),
    }


@router.get("")
async def list_contacts(
    account_id: int | None = None,
    q: str = "",
    tag: str = "",
    page: int = 1,
    size: int = 30,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user),
):
    stmt = select(Contact)
    if account_id:
        stmt = stmt.where(Contact.account_id == account_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Contact.first_name.like(like), Contact.username.like(like), Contact.note.like(like)))
    rows = (await db.execute(stmt.order_by(desc(Contact.last_msg_at)).limit(500))).scalars().all()
    if tag:
        rows = [c for c in rows if tag in (c.tags or [])]

    out = []
    for c in rows:
        last = (
            await db.execute(
                select(Message).where(Message.contact_id == c.id).order_by(desc(Message.created_at)).limit(1)
            )
        ).scalar_one_or_none()
        total = (
            await db.execute(select(func.count(Message.id)).where(Message.contact_id == c.id))
        ).scalar() or 0
        out.append(
            ser(c, {
                "last_message": (last.text[:60] if last else ""),
                "last_direction": last.direction if last else "",
                "message_count": total,
            })
        )
    start = (page - 1) * size
    return {"total": len(out), "items": out[start : start + size]}


@router.get("/{contact_id}")
async def contact_detail(contact_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    c = await db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "联系人不存在")
    facts = (
        await db.execute(
            select(MemoryFact).where(MemoryFact.contact_id == contact_id).order_by(desc(MemoryFact.weight))
        )
    ).scalars().all()
    acc = await db.get(Account, c.account_id)
    return ser(c, {
        "facts": [
            {
                "id": f.id, "category": f.category, "content": f.content, "weight": f.weight,
                "due_at": f.due_at.isoformat() if f.due_at else None,
                "created_at": f.created_at.isoformat(),
            }
            for f in facts
        ],
        "account_label": acc.label if acc else "",
    })


@router.patch("/{contact_id}")
async def update_contact(
    contact_id: int,
    body: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user),
):
    c = await db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "联系人不存在")
    data = body.model_dump(exclude_unset=True)
    mute_minutes = data.pop("mute_minutes", None)
    for k, v in data.items():
        if v is not None:
            setattr(c, k, v)
    if mute_minutes is not None:
        c.mute_until = (
            datetime.now(timezone.utc) + timedelta(minutes=mute_minutes) if mute_minutes > 0 else None
        )
    await audit(db, actor=user["sub"], action="contact_updated", object_type="contact", object_id=contact_id,
                detail={k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "note"})
    await db.commit()
    return ser(c)


@router.post("/{contact_id}/cold_start")
async def cold_start(contact_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    from ..workers.queue import enqueue

    queued = enqueue("app.workers.tasks.cold_start", contact_id)
    if queued.get("queued"):
        return {"queued": True, "job_id": queued["job_id"], "msg": "已提交后台队列"}
    try:
        return await cold_start_job(contact_id)
    except Exception as e:
        raise HTTPException(400, f"冷启动失败：{e}")


@router.delete("/{contact_id}")
async def delete_contact(contact_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    c = await db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "联系人不存在")
    await db.delete(c)
    await audit(db, actor=user["sub"], action="contact_deleted", object_type="contact", object_id=contact_id)
    await db.commit()
    return {"ok": True}


@router.get("/{contact_id}/facts")
async def list_facts(contact_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    rows = (
        await db.execute(select(MemoryFact).where(MemoryFact.contact_id == contact_id).order_by(desc(MemoryFact.created_at)))
    ).scalars().all()
    return [
        {
            "id": f.id, "category": f.category, "content": f.content, "weight": f.weight,
            "due_at": f.due_at.isoformat() if f.due_at else None,
            "created_at": f.created_at.isoformat(),
        }
        for f in rows
    ]


@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    f = await db.get(MemoryFact, fact_id)
    if not f:
        raise HTTPException(404, "记忆不存在")
    await db.delete(f)
    await audit(db, actor=user["sub"], action="fact_deleted", object_type="fact", object_id=fact_id)
    await db.commit()
    return {"ok": True}
