"""专属控制 bot：这套系统的远程控制台。

- 在 Telegram 里完成账号绑定（手机号 → 验证码 → 两步验证），不需要网页后台
- 查看账号在线状态、切换人设、单账号/全局开关、按人联系停发
- 一条指令做真实的链路自检（模型连通、语音、依赖、账号数）

独立于被接管的个人账号，动作用的是 Bot API 身份，只做控制面，不参与对话。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

from sqlalchemy import select
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from ..config import settings as env
from ..db import SessionLocal
from ..core import bins
from ..models import Account, AuditLog, Contact, ControlCommandLog, Persona, Setting
from . import login as loginmod
from .manager import manager

log = logging.getLogger("tg.controlbot")

_client: TelegramClient | None = None
_task = None
_api_task: asyncio.Task | None = None

# 两条通道（MTProto 与 Bot API 长轮询）可能同时收到同一条消息，按 (chat_id, message_id) 去重
_SEEN: set[tuple[int, int]] = set()
_SEEN_ORDER: list[tuple[int, int]] = []

# 每个操作人自己的登录流程，互不干扰
_pending_login: dict[int, int] = {}

HELP = (
    "【绑定账号】\n"
    "/login +85512345678  开始登录（验证码会发到你 Telegram）\n"
    "/code 12345          填验证码\n"
    "/pass 你的二级密码    开了两步验证才需要\n"
    "/cancel              放弃本次登录\n\n"
    "【看状态】\n"
    "/status   账号状态（在线/停发/待登录）\n"
    "/personas 人设清单\n"
    "/diag     系统自检（模型、语音、依赖）\n"
    "/test     真跑一次模型，验证能不能回话\n\n"
    "【控制】\n"
    "/use 账号号 人设号   给账号指定人设\n"
    "/on 号  /off 号      开/关某个账号的 AI\n"
    "/stop  /resume       全部停发 / 全部恢复\n"
    "/skip @某人          今天别回这个人\n"
    "/unskip @某人        恢复回复\n"
    "/takeover @某人      人工接管 2 小时"
)


async def _cfg(db) -> dict:
    row = await db.get(Setting, "control_bot")
    return (row.value if row else {}) or {}


async def _save_cfg(db, cfg: dict) -> None:
    row = await db.get(Setting, "control_bot")
    if row:
        row.value = cfg
    else:
        db.add(Setting(key="control_bot", value=cfg))


def _token() -> str:
    return (env.CONTROL_BOT_TOKEN or "").strip()


async def start_control_bot() -> None:
    global _client
    token = _token()
    if not token:
        log.info("未配置控制 bot token，跳过")
        return
    if not env.TG_API_ID or not env.TG_API_HASH:
        log.warning("控制 bot 缺 TG_API_ID/TG_API_HASH，暂不启动")
        return
    _client = TelegramClient(
        StringSession(), int(env.TG_API_ID), env.TG_API_HASH, connection_retries=10, retry_delay=5
    )
    await _client.start(bot_token=token)
    me = await _client.get_me()

    @_client.on(events.NewMessage(incoming=True))
    async def _handler(event):  # noqa: ANN001
        key = (int(getattr(event, "chat_id", 0) or 0), int(getattr(getattr(event, "message", None), "id", 0) or 0))
        if key[1] and _seen(key):
            return
        try:
            await _handle(event)
        except Exception as e:  # 指令出错不能把控制 bot 带崩
            log.exception("控制指令异常: %s", e)
            try:
                await event.reply(f"这条没办成：{type(e).__name__}: {str(e)[:200]}")
            except Exception:
                pass

    start_api_channel()
    start_heartbeat()
    await _setup_commands()
    log.info("控制 bot 已启动 @%s（双通道接收）", getattr(me, "username", "?"))





COMMANDS = [
    ("start", "开始 / 查看全部指令"),
    ("status", "账号状态：在线、停发、人设"),
    ("login", "绑定账号（发 /login +手机号）"),
    ("code", "填登录验证码"),
    ("pass", "填两步验证密码"),
    ("personas", "看 12 个人设"),
    ("use", "给账号换人设"),
    ("on", "开某个账号的 AI"),
    ("off", "关某个账号的 AI"),
    ("stop", "全部停发（急停）"),
    ("resume", "全部恢复"),
    ("skip", "今天别回某个人"),
    ("takeover", "人工接管某人 2 小时"),
    ("diag", "系统自检"),
    ("test", "真跑一次模型"),
    ("help", "指令表"),
]


async def _setup_commands() -> None:
    """把指令挂到 Telegram 的菜单里，点一下就能用。"""
    token = _token()
    if not token:
        return
    base = f"https://api.telegram.org/bot{token}"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            await c.post(
                f"{base}/setMyCommands",
                json={"commands": [{"command": k, "description": v} for k, v in COMMANDS]},
            )
            await c.post(
                f"{base}/setMyDescription",
                json={"description": "你的账号自动聊天中控台：绑号、换人设、开关 AI、急停，全在聊天里完成。"},
            )
    except Exception as e:
        log.warning("设置菜单失败（不影响指令使用）: %s", e)


_heartbeat_task: asyncio.Task | None = None


async def _heartbeat_loop() -> None:
    """每 5 分钟把在线时间写进 bot 简介（可被外部读回，用来确认进程真在跑）。"""
    token = _token()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/setMyShortDescription"
    while True:
        try:
            now = datetime.now(timezone.utc).strftime("%m-%d %H:%MZ")
            model = (env.LLM_MODEL or "").split("/")[-1][:18]
            desc = f"在线 {now} · {model}"
            async with httpx.AsyncClient(timeout=20) as c:
                await c.post(url, json={"short_description": desc})
        except Exception:
            pass
        await asyncio.sleep(300)


def start_heartbeat() -> None:
    global _heartbeat_task
    if _heartbeat_task and not _heartbeat_task.done():
        return
    _heartbeat_task = asyncio.create_task(_heartbeat_loop(), name="control-heartbeat")


def _preset_admins() -> list[int]:
    raw = (env.CONTROL_ADMIN_IDS or "").replace(";", ",").replace(" ", ",")
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def _seen(key: tuple[int, int]) -> bool:
    """记下这条消息；返回 True 表示已经处理过（另一条通道重复送达）。"""
    if key in _SEEN:
        return True
    _SEEN.add(key)
    _SEEN_ORDER.append(key)
    while len(_SEEN_ORDER) > 800:
        old = _SEEN_ORDER.pop(0)
        _SEEN.discard(old)
    return False


async def _api_send(chat_id: int, text: str) -> None:
    token = _token()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as c:
        for chunk in [text[i : i + 3800] for i in range(0, len(text), 3800)]:
            try:
                await c.post(url, json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True})
            except Exception as e:
                log.warning("回复失败: %s", e)
                return


class _ApiEvent:
    """把 Bot API 的一条消息包装成和 Telethon 事件一样的用法。"""

    def __init__(self, msg: dict):
        self.msg = msg
        self.chat_id = int((msg.get("chat") or {}).get("id") or 0)
        self.message = SimpleNamespace(id=int(msg.get("message_id") or 0))

    @property
    def raw_text(self) -> str:
        return (self.msg.get("text") or self.msg.get("caption") or "").strip()

    async def get_sender(self):
        frm = self.msg.get("from") or {}
        return SimpleNamespace(id=int(frm.get("id") or 0), first_name=frm.get("first_name") or "")

    async def reply(self, text: str) -> None:
        await _api_send(self.chat_id, text)


async def _poll_api_channel() -> None:
    """Bot API 长轮询：和 MTProto 并行，哪条先到走哪条，保证消息不会卡在队列里。"""
    token = _token()
    if not token:
        return
    base = f"https://api.telegram.org/bot{token}"
    offset: int | None = None
    # 启动时把历史积压跳过：旧消息不再补回复，避免一开机刷你一脸
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{base}/getUpdates", params={"offset": -1, "timeout": 0})
            res = r.json().get("result") or []
            if res:
                offset = int(res[-1]["update_id"]) + 1
        if offset:
            log.info("控制 bot 通道就绪，跳过 %s 条历史积压", 1)
    except Exception as e:
        log.warning("清空积压失败（不影响接收）: %s", e)

    while True:
        try:
            params = {"timeout": 25, "allowed_updates": '["message"]'}
            if offset is not None:
                params["offset"] = offset
            async with httpx.AsyncClient(timeout=40) as c:
                r = await c.get(f"{base}/getUpdates", params=params)
            data = r.json()
            if not data.get("ok"):
                log.warning("Bot API 轮询异常: %s", str(data)[:200])
                await asyncio.sleep(5)
                continue
            for u in data.get("result") or []:
                offset = int(u["update_id"]) + 1
                msg = u.get("message") or u.get("edited_message")
                if not msg:
                    continue
                key = (int((msg.get("chat") or {}).get("id") or 0), int(msg.get("message_id") or 0))
                if key[1] and _seen(key):
                    continue
                try:
                    await _handle(_ApiEvent(msg))
                except Exception as e:
                    log.exception("处理消息失败: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("轮询中断，重试: %s", e)
            await asyncio.sleep(3)


def start_api_channel() -> None:
    global _api_task
    if not _token():
        return
    if _api_task and not _api_task.done():
        return
    _api_task = asyncio.create_task(_poll_api_channel(), name="control-bot-updates")


async def _reply(event, text: str) -> None:
    for chunk in [text[i : i + 3800] for i in range(0, len(text), 3800)]:
        await event.reply(chunk)


async def _handle(event) -> None:
    text = (event.raw_text or "").strip()
    if not text:
        return
    sender = await event.get_sender()
    sid = getattr(sender, "id", 0) or 0

    async with SessionLocal() as db:
        cfg = await _cfg(db)
        preset = _preset_admins()
        if preset:
            if list(cfg.get("admin_ids") or []) != preset:
                cfg["admin_ids"] = preset
                await _save_cfg(db, cfg)
                await db.commit()
            admins = preset
        else:
            admins = list(cfg.get("admin_ids") or [])
        if not admins:
            # 第一个跟这个 bot 说话的人即主人（token 只有你能拿到）
            cfg["admin_ids"] = [sid]
            await _save_cfg(db, cfg)
            await db.commit()
            await _reply(
                event,
                f"已登记你（{sid}）为唯一控制者，之后只有你能下指令。\n\n{HELP}",
            )
            return
        if sid not in admins:
            await _reply(event, "没有权限。")
            return

    if not text.startswith("/"):
        await _reply(event, HELP)
        return

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    # ---- 需要在会话外做网络动作的指令 ----
    if cmd == "/login":
        await _reply(event, await _do_login(sid, arg))
        return
    if cmd == "/code":
        await _reply(event, await _do_code(sid, arg))
        return
    if cmd == "/pass":
        await _reply(event, await _do_pass(sid, arg))
        return
    if cmd == "/cancel":
        aid = _pending_login.pop(sid, None)
        if aid:
            await loginmod.abort_login(aid)
        await _reply(event, "已放弃本次登录。")
        return
    if cmd == "/test":
        await _reply(event, await _do_test())
        return

    result = ""
    async with SessionLocal() as db:
        if cmd in ("/help", "/start", "/menu"):
            result = HELP
        elif cmd == "/status":
            rows = (await db.execute(select(Account).order_by(Account.id))).scalars().all()
            if not rows:
                result = "还没有账号。发 /login +你的手机号 开始绑定。"
            else:
                lines = []
                for a in rows:
                    p = await db.get(Persona, a.persona_id) if a.persona_id else None
                    state = {"online": "在线", "offline": "离线", "waiting_code": "等验证码",
                             "waiting_2fa": "等二级密码", "error": "异常"}.get(a.status, a.status)
                    lines.append(
                        f"#{a.id} {a.label or a.phone} · {state} · AI{'开' if a.ai_enabled else '关'}"
                        f" · 人设：{p.name if p else '未指定'}"
                        + (f"\n    └ {a.last_error[:80]}" if a.last_error else "")
                    )
                result = "\n".join(lines)
        elif cmd == "/personas":
            rows = (await db.execute(select(Persona).order_by(Persona.id))).scalars().all()
            if not rows:
                result = "还没有人设。"
            else:
                result = "\n".join(
                    f"{p.id}. {p.name} · {p.gender} · {p.default_language} · 语音比例{p.voice_ratio}%"
                    for p in rows
                ) + "\n\n用法：/use 账号号 人设号"
        elif cmd == "/diag":
            result = await _diag(db)
        elif cmd == "/use":
            nums = arg.split()
            try:
                aid, pid = int(nums[0]), int(nums[1])
            except (IndexError, ValueError):
                result = "用法：/use 账号号 人设号（先发 /status、/personas 看编号）"
            else:
                acc = await db.get(Account, aid)
                p = await db.get(Persona, pid)
                if not acc or not p:
                    result = "账号或人设编号不存在。"
                else:
                    acc.persona_id = p.id
                    result = f"✅ 账号 #{acc.id} 已切到人设「{p.name}」"
        elif cmd in ("/on", "/off"):
            try:
                aid = int(arg)
            except ValueError:
                result = f"用法：{cmd} 账号号"
            else:
                acc = await db.get(Account, aid)
                if not acc:
                    result = "账号不存在。"
                else:
                    acc.ai_enabled = cmd == "/on"
                    acc.auto_reply = cmd == "/on"
                    result = f"账号 #{acc.id} AI 已{'开启' if acc.ai_enabled else '关闭'}。"
        elif cmd == "/stop":
            rows = (await db.execute(select(Account))).scalars().all()
            for a in rows:
                a.ai_enabled = False
            result = f"已全部停发（{len(rows)} 个账号），立即生效。"
        elif cmd == "/resume":
            rows = (await db.execute(select(Account))).scalars().all()
            for a in rows:
                a.ai_enabled = True
                a.auto_reply = True
            result = f"已全部恢复（{len(rows)} 个账号）。"
        elif cmd in ("/skip", "/unskip", "/takeover"):
            username = arg.lstrip("@")
            contacts = (
                await db.execute(select(Contact).where(Contact.username == username))
            ).scalars().all()
            if not contacts:
                result = f"没找到 @{username} 的会话记录（还没聊过就发不出这条指令）。"
            else:
                for c in contacts:
                    if cmd == "/skip":
                        c.ai_enabled = False
                    elif cmd == "/unskip":
                        c.ai_enabled = True
                    else:
                        c.mute_until = datetime.now(timezone.utc) + timedelta(hours=2)
                result = f"已处理 {len(contacts)} 个 @{username} 的会话。"
        else:
            result = "没这条指令。\n\n" + HELP

        db.add(ControlCommandLog(source="bot", command=cmd, target=arg, result=result[:300]))
        db.add(
            AuditLog(
                actor=f"bot:{sid}",
                action=f"control{cmd}",
                object_type="account",
                object_id=arg,
                detail={"text": text[:200]},
            )
        )
        await db.commit()

    await _reply(event, result)


# ---------------- 具体动作 ----------------
async def _do_login(sid: int, phone: str) -> str:
    phone = phone.replace(" ", "").replace("-", "")
    if not phone.startswith("+") or len(phone) < 8:
        return "用法：/login +85512345678（国际格式，带 + 和国家码）"

    async with SessionLocal() as db:
        acc = (
            await db.execute(select(Account).where(Account.phone == phone))
        ).scalars().first()
        if not acc:
            acc = Account(
                phone=phone,
                label=phone,
                api_id=str(env.TG_API_ID or ""),
                api_hash=env.TG_API_HASH or "",
            )
            db.add(acc)
            await db.commit()
            await db.refresh(acc)
        aid = acc.id

    try:
        info = await loginmod.send_code(aid)
    except Exception as e:
        return f"验证码没发出去：{type(e).__name__}: {str(e)[:200]}"
    _pending_login[sid] = aid
    return (
        f"账号 #{aid} {phone}\n{info['hint']}\n\n"
        "收到后发：/code 12345\n开了两步验证的话，验证码通过后我会再找你要密码。"
    )


async def _do_code(sid: int, code: str) -> str:
    aid = _pending_login.get(sid)
    if not aid:
        return "现在没有等待中的登录。先发 /login +手机号"
    code = code.strip().replace(" ", "")
    if not code:
        return "用法：/code 12345"
    try:
        res = await loginmod.verify_code(aid, code)
    except Exception as e:
        return f"验证没通过：{type(e).__name__}: {str(e)[:200]}\n可以重发 /code 再试一次。"
    if res.get("need_password"):
        return "这个号开了两步验证 🔐 发 /pass 你的二级密码"
    _pending_login.pop(sid, None)
    return (
        f"✅ 登录成功：{res.get('self_name', '')}（{res.get('self_id')}）\n"
        "账号已上线，AI 现在开始接管回复。发 /status 看状态。"
    )


async def _do_pass(sid: int, password: str) -> str:
    aid = _pending_login.get(sid)
    if not aid:
        return "现在没有等待中的登录。先发 /login +手机号"
    if not password:
        return "用法：/pass 你的二级密码"
    try:
        res = await loginmod.submit_password(aid, password)
    except Exception as e:
        return f"密码没通过：{type(e).__name__}: {str(e)[:200]}"
    _pending_login.pop(sid, None)
    return f"✅ 登录成功：{res.get('self_name', '')}（{res.get('self_id')}），AI 已接管。"


async def _do_test() -> str:
    from ..core.llm import LLMError, get_client

    async with SessionLocal() as db:
        try:
            llm, cfg = await get_client(db)
        except LLMError as e:
            return f"模型没配好：{e}"
    try:
        text, usage = await llm.chat(
            [
                {"role": "system", "content": "你是一个连通性测试，一句话回答。"},
                {"role": "user", "content": "用一句中文说：连接正常"},
            ],
            max_tokens=40,
        )
    except LLMError as e:
        return f"模型调用失败：{str(e)[:300]}"
    return f"✅ 模型正常\n型号：{usage.get('model')}\n耗时：{usage.get('elapsed_ms')}ms\n回复：{text[:120]}"


async def _diag(db) -> str:
    from sqlalchemy import func

    accounts = (await db.execute(select(func.count(Account.id)))).scalar() or 0
    online = (
        await db.execute(select(func.count(Account.id)).where(Account.status == "online"))
    ).scalar() or 0
    personas = (await db.execute(select(func.count(Persona.id)))).scalar() or 0
    contacts = (await db.execute(select(func.count(Contact.id)))).scalar() or 0
    return (
        "【自检】\n"
        f"模型：{env.LLM_MODEL or '未配置'}\n"
        f"Telegram 应用凭据：{'已配置' if env.TG_API_ID and env.TG_API_HASH else '缺'}\n"
        f"语音合成：{env.TTS_PROVIDER}（ffmpeg {'可用' if bins.available(env.FFMPEG_BIN, "ffmpeg") else '缺失'}）\n"
        f"语音转写：{env.ASR_BACKEND}\n"
        f"账号：{accounts} 个（在线 {online}）· 人设 {personas} 个 · 会话 {contacts} 个\n"
        f"存放：{'SQLite 本地库' if 'sqlite' in env.DATABASE_URL else 'PostgreSQL'}"
    )


async def stop_control_bot() -> None:
    global _client, _api_task
    if _api_task:
        _api_task.cancel()
        _api_task = None
    if _client:
        try:
            await _client.disconnect()
        except Exception:
            pass
        _client = None
