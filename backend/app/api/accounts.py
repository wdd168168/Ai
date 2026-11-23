"""账户接入：多账号、登录、代理、设备指纹、启停、限速。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.ratelimit import RateLimiter
from ..db import get_db
from ..deps import audit, current_user
from ..models import Account, Contact, Message, Persona
from ..schemas import AccountIn, AccountUpdate, VerifyCodeIn
from ..tg import login as login_flow
from ..tg.manager import manager

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def ser(a: Account, persona_name: str = "", extra: dict | None = None) -> dict:
    return {
        "id": a.id,
        "label": a.label,
        "phone": a.phone,
        "status": a.status,
        "last_error": a.last_error,
        "enabled": a.enabled,
        "ai_enabled": a.ai_enabled,
        "auto_reply": a.auto_reply,
        "proactive_enabled": a.proactive_enabled,
        "persona_id": a.persona_id,
        "persona_name": persona_name,
        "device_model": a.device_model,
        "system_version": a.system_version,
        "app_version": a.app_version,
        "lang_code": a.lang_code,
        "proxy": a.proxy,
        "rate_limits": a.rate_limits,
        "tg_self_name": a.tg_self_name,
        "tg_self_id": a.tg_self_id,
        "has_session": bool(a.session_enc),
        "warmup_started_at": a.warmup_started_at.isoformat() if a.warmup_started_at else None,
        "last_connected_at": a.last_connected_at.isoformat() if a.last_connected_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        **(extra or {}),
    }


@router.get("")
async def list_accounts(user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Account).order_by(Account.id))).scalars().all()
    out = []
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for a in rows:
        pname = ""
        if a.persona_id:
            p = await db.get(Persona, a.persona_id)
            pname = p.name if p else ""
        contacts = (
            await db.execute(select(func.count(Contact.id)).where(Contact.account_id == a.id))
        ).scalar() or 0
        msgs_today = (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.account_id == a.id, Message.direction == "out", Message.created_at >= today
                )
            )
        ).scalar() or 0
        stats = await RateLimiter(a).stats()
        runner = manager.runners.get(a.id)
        live = "online" if (runner and runner.client and runner.client.is_connected()) else a.status
        out.append(ser(a, pname, {"contacts": contacts, "sent_today": msgs_today, "limits_live": stats, "live_status": live}))
    return out


@router.post("")
async def create_account(
    body: AccountIn, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    exists = (await db.execute(select(Account).where(Account.phone == body.phone))).scalar_one_or_none()
    if exists:
        raise HTTPException(400, "这个手机号已经添加过了")
    acc = Account(
        label=body.label or body.phone,
        phone=body.phone,
        api_id=body.api_id,
        api_hash=body.api_hash,
        device_model=body.device_model,
        system_version=body.system_version,
        app_version=body.app_version,
        lang_code=body.lang_code,
        proxy=body.proxy,
        rate_limits=body.rate_limits,
        persona_id=body.persona_id,
        status="offline",
    )
    db.add(acc)
    await db.flush()
    await audit(db, actor=user["sub"], action="account_created", object_type="account", object_id=acc.id,
                detail={"phone": body.phone, "label": acc.label})
    await db.commit()
    return ser(acc)


@router.patch("/{account_id}")
async def update_account(
    account_id: int,
    body: AccountUpdate,
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    acc = await db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "账号不存在")
    changed = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        setattr(acc, field, value)
        changed[field] = value if field not in ("proxy",) else "***"
    await audit(db, actor=user["sub"], action="account_updated", object_type="account",
                object_id=account_id, detail=changed)
    await db.commit()
    return ser(acc)


@router.delete("/{account_id}")
async def delete_account(
    account_id: int, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    acc = await db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "账号不存在")
    await manager.stop_account(account_id)
    await audit(db, actor=user["sub"], action="account_deleted", object_type="account",
                object_id=account_id, detail={"phone": acc.phone})
    await db.delete(acc)
    await db.commit()
    return {"ok": True}


# ---------- 登录流程 ----------
@router.post("/{account_id}/login/send_code")
async def send_code(account_id: int, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    acc = await db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "账号不存在")
    try:
        res = await login_flow.send_code(account_id)
    except Exception as e:
        raise HTTPException(400, f"发送验证码失败：{e}")
    await audit(db, actor=user["sub"], action="login_send_code", object_type="account", object_id=account_id)
    await db.commit()
    return res


@router.post("/{account_id}/login/verify")
async def verify_code(
    account_id: int,
    body: VerifyCodeIn,
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        res = await login_flow.verify_code(account_id, body.code, body.password)
    except Exception as e:
        raise HTTPException(400, f"登录失败：{e}")
    await audit(db, actor=user["sub"], action="login_verified", object_type="account",
                object_id=account_id, detail={"need_password": res.get("need_password", False)})
    await db.commit()
    return res


@router.post("/{account_id}/login/abort")
async def abort_login(account_id: int, user: dict = Depends(current_user)):
    await login_flow.abort_login(account_id)
    return {"ok": True}


# ---------- 运行控制 ----------
@router.post("/{account_id}/start")
async def start_account(account_id: int, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    acc = await db.get(Account, account_id)
    if not acc or not acc.session_enc:
        raise HTTPException(400, "账号还没有完成登录")
    await manager.start_account(account_id)
    await audit(db, actor=user["sub"], action="account_started", object_type="account", object_id=account_id)
    await db.commit()
    return {"ok": True}


@router.post("/{account_id}/stop")
async def stop_account(account_id: int, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await manager.stop_account(account_id)
    await audit(db, actor=user["sub"], action="account_stopped", object_type="account", object_id=account_id)
    await db.commit()
    return {"ok": True}


@router.post("/{account_id}/restart")
async def restart_account(account_id: int, user: dict = Depends(current_user)):
    await manager.restart_account(account_id)
    return {"ok": True}


@router.get("/{account_id}/limits")
async def account_limits(account_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    acc = await db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "账号不存在")
    return await RateLimiter(acc).stats()


@router.get("/{account_id}/dialogs")
async def dialogs(account_id: int, limit: int = 60, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """拉真实 Telegram 会话列表（用于挑选联系人/建立主动任务对象）。"""
    runner = manager.runners.get(account_id)
    if not runner or not runner.client:
        raise HTTPException(400, "账号未在线，先启动账号")
    out = []
    async for d in runner.client.iter_dialogs(limit=limit):
        if not d.is_user:
            continue
        e = d.entity
        out.append(
            {
                "tg_id": e.id,
                "name": " ".join(filter(None, [getattr(e, "first_name", ""), getattr(e, "last_name", "")])),
                "username": getattr(e, "username", None),
                "last_message": (d.message.message or "")[:80] if d.message else "",
                "date": d.date.isoformat() if d.date else None,
            }
        )
    return out
