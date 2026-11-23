"""账号登录流程：手机号 + 验证码 + 两步验证，成功后落加密 session。"""
from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from ..config import settings
from ..db import SessionLocal
from ..models import Account
from ..core import security
from .manager import AccountRunner

log = logging.getLogger("tg.login")

# account_id -> {client, phone, phone_code_hash}
_PENDING: dict[int, dict] = {}


def _build_client(acc: Account) -> TelegramClient:
    proxy = AccountRunner._build_proxy(acc.proxy or {})
    return TelegramClient(
        StringSession(),
        int(acc.api_id or settings.TG_API_ID or 0),
        acc.api_hash or settings.TG_API_HASH or "",
        device_model=acc.device_model,
        system_version=acc.system_version,
        app_version=acc.app_version,
        lang_code=acc.lang_code,
        proxy=proxy,
    )


async def send_code(account_id: int) -> dict:
    async with SessionLocal() as db:
        acc = await db.get(Account, account_id)
        if not acc:
            raise RuntimeError("账号不存在")
        if not (acc.api_id or settings.TG_API_ID) or not (acc.api_hash or settings.TG_API_HASH):
            raise RuntimeError("缺少 api_id / api_hash：请先在系统设置里配置平台应用凭据，或在账号里单独填写")
        phone = acc.phone
        client = _build_client(acc)

    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    except Exception:
        await client.disconnect()
        raise
    _PENDING[account_id] = {
        "client": client,
        "phone": phone,
        "phone_code_hash": sent.phone_code_hash,
        "sent_at": sent.timeout,
    }
    code_type = type(sent.type).__name__ if sent.type else "unknown"
    # 能收到短信/语音的提示，前端据此显示
    hint = {
        "SentCodeTypeApp": "验证码已发到你的 Telegram 客户端（已在其他设备登录）",
        "SentCodeTypeSms": "验证码已通过短信发送",
        "SentCodeTypeCall": "将以电话语音播报验证码",
        "SentCodeTypeFlashCall": "注意来电号码，验证码在号码里",
        "SentCodeTypeEmailCode": "验证码已发到邮箱",
        "SentCodeTypeFragmentSms": "需要付费通道（官方付费短信）",
    }.get(code_type, f"验证码已发送（{code_type}）")
    async with SessionLocal() as db:
        acc = await db.get(Account, account_id)
        if acc:
            acc.status = "waiting_code"
            await db.commit()
    return {"code_type": code_type, "hint": hint, "timeout": getattr(sent, "timeout", None)}


async def verify_code(account_id: int, code: str, password: str = "") -> dict:
    st = _PENDING.get(account_id)
    if not st:
        raise RuntimeError("请先获取验证码")
    client: TelegramClient = st["client"]
    phone = st["phone"]

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=st["phone_code_hash"])
    except SessionPasswordNeededError:
        if not password:
            async with SessionLocal() as db:
                acc = await db.get(Account, account_id)
                if acc:
                    acc.status = "waiting_2fa"
                    await db.commit()
            return {"need_password": True, "hint": "该账号开启了两步验证，请输入密码"}
        await client.sign_in(password=password)
    except Exception:
        raise

    return await _finalize(account_id, client)


async def submit_password(account_id: int, password: str) -> dict:
    """两步验证：用已发出的登录流程补二级密码，成功后落 session 并上线。"""
    st = _PENDING.get(account_id)
    if not st:
        raise RuntimeError("登录流程已失效，请重新发 /login 手机号")
    client: TelegramClient = st["client"]
    await client.sign_in(password=password)
    return await _finalize(account_id, client)


async def _finalize(account_id: int, client: TelegramClient) -> dict:
    me = await client.get_me()
    session_str = StringSession.save(client.session)
    enc = security.encrypt_session(session_str)

    async with SessionLocal() as db:
        acc = await db.get(Account, account_id)
        if not acc:
            await client.disconnect()
            raise RuntimeError("账号不存在")
        acc.session_enc = enc
        acc.status = "online"
        acc.last_error = ""
        acc.tg_self_id = me.id if me else None
        acc.tg_self_name = " ".join(filter(None, [me.first_name, me.last_name])) if me else ""
        from datetime import datetime, timezone

        if not acc.warmup_started_at:
            acc.warmup_started_at = datetime.now(timezone.utc)
        await db.commit()

    _PENDING.pop(account_id, None)
    await client.disconnect()

    # 启动常驻 runner
    from .manager import manager

    await manager.start_account(account_id)
    return {"ok": True, "self_name": me.first_name if me else "", "self_id": me.id if me else None}


async def abort_login(account_id: int) -> None:
    st = _PENDING.pop(account_id, None)
    if st:
        try:
            await st["client"].disconnect()
        except Exception:
            pass
