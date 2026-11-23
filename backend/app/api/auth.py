"""登录 / 2FA / 账户安全。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import security
from ..db import get_db
from ..deps import audit, client_ip, current_user
from ..models import User
from ..schemas import LoginIn, PasswordChange, TokenOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    ip = client_ip(request)
    if not user or not user.is_active or not security.verify_password(body.password, user.password_hash):
        await audit(db, actor=body.username, action="login_failed", detail={"ip": ip}, ip=ip)
        await db.commit()
        raise HTTPException(401, "用户名或密码错误")
    if user.totp_enabled:
        if not body.totp:
            raise HTTPException(401, "需要两步验证码")
        if not security.verify_totp(user.totp_secret or "", body.totp):
            await audit(db, actor=body.username, action="login_2fa_failed", ip=ip)
            await db.commit()
            raise HTTPException(401, "两步验证码不正确")
    token = security.create_token(user.username, user.role)
    await audit(db, actor=user.username, action="login", ip=ip)
    await db.commit()
    return TokenOut(access_token=token, username=user.username, totp_enabled=user.totp_enabled)


@router.get("/me")
async def me(user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    u = (await db.execute(select(User).where(User.username == user["sub"]))).scalar_one_or_none()
    if not u:
        raise HTTPException(401, "用户不存在")
    return {"username": u.username, "role": u.role, "totp_enabled": u.totp_enabled}


@router.post("/password")
async def change_password(
    body: PasswordChange,
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    u = (await db.execute(select(User).where(User.username == user["sub"]))).scalar_one_or_none()
    if not u or not security.verify_password(body.old_password, u.password_hash):
        raise HTTPException(400, "原密码不正确")
    ok, msg = security.password_strength(body.new_password)
    if not ok:
        raise HTTPException(400, msg)
    u.password_hash = security.hash_password(body.new_password)
    await audit(db, actor=u.username, action="password_changed")
    await db.commit()
    return {"ok": True}


@router.post("/2fa/setup")
async def setup_2fa(user: dict = Depends(current_user)):
    secret = security.new_totp_secret()
    return {"secret": secret, "uri": security.totp_uri(secret, user["sub"])}


@router.post("/2fa/enable")
async def enable_2fa(
    body: dict,
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    secret = (body.get("secret") or "").strip()
    code = (body.get("code") or "").strip()
    if not security.verify_totp(secret, code):
        raise HTTPException(400, "验证码不正确，请确认手机上的动态码")
    u = (await db.execute(select(User).where(User.username == user["sub"]))).scalar_one_or_none()
    u.totp_secret = secret
    u.totp_enabled = True
    await audit(db, actor=u.username, action="2fa_enabled")
    await db.commit()
    return {"ok": True}


@router.post("/2fa/disable")
async def disable_2fa(
    body: dict,
    user: dict = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    u = (await db.execute(select(User).where(User.username == user["sub"]))).scalar_one_or_none()
    if not security.verify_password(body.get("password", ""), u.password_hash):
        raise HTTPException(400, "密码不正确")
    u.totp_enabled = False
    u.totp_secret = None
    await audit(db, actor=u.username, action="2fa_disabled")
    await db.commit()
    return {"ok": True}
