"""Telegram 接入层：多账号 MTProto 客户端池。

- 一号一会话（Fernet 加密存库），重启免登录
- 设备指纹稳定、可配置
- SOCKS5 / MTProxy 一账号一出口
- 单账号异常隔离，不影响其它账号
- FloodWait 精确等待，绝不重试轰炸
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError
from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeAudio

from ..config import settings
from ..db import SessionLocal
from ..models import Account
from ..core import security
from ..core.ratelimit import RateLimiter

log = logging.getLogger("tg.manager")


class AccountRunner:
    """一个账号一个 runner：独立 client、独立任务、独立错误域。"""

    def __init__(self, account_id: int) -> None:
        self.account_id = account_id
        self.client: TelegramClient | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._backoff = 3
        self.status = "offline"
        self.last_error = ""

    # ---------- 生命周期 ----------
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_forever(), name=f"acct-{self.account_id}")

    async def _run_forever(self) -> None:
        while not self._stopping:
            try:
                await self._connect_once()
                self._backoff = 3
                # 常驻：等断开
                while self.client and self.client.is_connected() and not self._stopping:
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("account %s 断线: %s", self.account_id, self.last_error)
                await self._set_status("error", self.last_error)
            finally:
                if self.client:
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
                    self.client = None
            if self._stopping:
                break
            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, 300)

    async def _connect_once(self) -> None:
        async with SessionLocal() as db:
            acc = await db.get(Account, self.account_id)
            if not acc or not acc.session_enc or not acc.enabled:
                self._stopping = True
                return
            api_id = int(acc.api_id or settings.TG_API_ID or 0)
            api_hash = acc.api_hash or settings.TG_API_HASH
            proxy = self._build_proxy(acc.proxy or {})
            session = StringSession(security.decrypt_session(acc.session_enc))
            client = TelegramClient(
                session,
                api_id,
                api_hash,
                device_model=acc.device_model,
                system_version=acc.system_version,
                app_version=acc.app_version,
                lang_code=acc.lang_code,
                proxy=proxy,
                connection=ConnectionTcpMTProxyRandomizedIntermediate if (acc.proxy or {}).get("scheme") == "mtproxy" else None,
                retry_delay=5,
                auto_reconnect=True,
                connection_retries=10,
                request_retries=3,
            )
        await client.connect()
        if not await client.is_user_authorized():
            await self._set_status("offline", "会话失效，需要重新登录")
            await client.disconnect()
            self._stopping = True
            return

        me = await client.get_me()
        self.client = client
        async with SessionLocal() as db:
            acc = await db.get(Account, self.account_id)
            if acc:
                acc.status = "online"
                acc.last_error = ""
                acc.tg_self_id = me.id if me else None
                acc.tg_self_name = " ".join(filter(None, [me.first_name, me.last_name])) if me else ""
                acc.last_connected_at = datetime.now(timezone.utc)
                await db.commit()
        self._register_handlers(client)
        log.info("account %s 已上线 (%s)", self.account_id, me.id if me else "?")

    def _register_handlers(self, client: TelegramClient) -> None:
        from . import handlers

        client.add_event_handler(
            lambda e: handlers.on_incoming(self.account_id, e),
            events.NewMessage(incoming=True),
        )
        client.add_event_handler(
            lambda e: handlers.on_outgoing(self.account_id, e),
            events.NewMessage(outgoing=True),
        )

    @staticmethod
    def _build_proxy(p: dict):
        if not p or not p.get("host"):
            return None
        scheme = (p.get("scheme") or "socks5").lower()
        host, port = p["host"], int(p.get("port", 1080))
        if scheme in ("socks5", "socks4"):
            import socks

            kind = socks.SOCKS5 if scheme == "socks5" else socks.SOCKS4
            return (kind, host, port, True, p.get("user") or None, p.get("pass") or None)
        if scheme in ("http", "https"):
            return ("http", host, port, True, p.get("user") or None, p.get("pass") or None)
        if scheme == "mtproxy":
            # 格式：host:port:secret
            return (host, port, p.get("secret", ""))
        return None

    async def _set_status(self, status: str, error: str = "") -> None:
        self.status = status
        async with SessionLocal() as db:
            acc = await db.get(Account, self.account_id)
            if acc:
                acc.status = status
                acc.last_error = error[:500]
                await db.commit()

    async def stop(self) -> None:
        self._stopping = True
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
        await self._set_status("offline")

    # ---------- 发送 ----------
    async def _peer(self, tg_id: int):
        assert self.client
        try:
            return await self.client.get_input_entity(tg_id)
        except Exception:
            return tg_id

    async def read_history(self, entity, limit: int = 300) -> list[str]:
        """拉本人历史消息，用于风格学习（只取本人发出的）。"""
        assert self.client
        out: list[str] = []
        async for m in self.client.iter_messages(entity, limit=limit):
            if m.out and m.message:
                out.append(m.message)
        return out

    async def send_text(self, tg_id: int, text: str) -> int | None:
        assert self.client
        peer = await self._peer(tg_id)
        msg = await self.client.send_message(peer, text)
        return getattr(msg, "id", None)

    async def send_voice(self, tg_id: int, path: str, duration: float) -> int | None:
        assert self.client
        peer = await self._peer(tg_id)
        msg = await self.client.send_file(
            peer,
            path,
            voice_note=True,
            attributes=[DocumentAttributeAudio(voice=True, duration=int(max(1, duration)))],
        )
        return getattr(msg, "id", None)

    async def mark_read(self, tg_id: int) -> None:
        if not self.client:
            return
        try:
            await self.client.send_read_acknowledge(await self._peer(tg_id))
        except Exception:
            pass


class AccountManager:
    """全局账号池。"""

    def __init__(self) -> None:
        self.runners: dict[int, AccountRunner] = {}
        self._lock = asyncio.Lock()

    async def start_account(self, account_id: int) -> None:
        async with self._lock:
            if account_id in self.runners:
                return
            r = AccountRunner(account_id)
            self.runners[account_id] = r
        await r.start()

    async def stop_account(self, account_id: int) -> None:
        async with self._lock:
            r = self.runners.pop(account_id, None)
        if r:
            await r.stop()

    async def restart_account(self, account_id: int) -> None:
        await self.stop_account(account_id)
        await self.start_account(account_id)

    def get(self, account_id: int) -> AccountRunner | None:
        r = self.runners.get(account_id)
        return r if r and r.client and r.client.is_connected() else r

    async def restore_all(self) -> None:
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(Account).where(Account.enabled == True, Account.session_enc.is_not(None))  # noqa: E712
                )
            ).scalars().all()
        for acc in rows:
            try:
                await self.start_account(acc.id)
            except Exception as e:
                log.warning("恢复账号 %s 失败: %s", acc.id, e)


manager = AccountManager()


async def human_send(
    *,
    account_id: int,
    tg_id: int,
    text: str,
    plan,
    voice_path: str = "",
    voice_duration: float = 0.0,
) -> list[int]:
    """按发送计划执行：已读延迟 → 逐条 typing → 发送 → 条间间隔。返回 tg message id 列表。"""
    runner = manager.runners.get(account_id)
    if not runner or not runner.client:
        raise RuntimeError("账号未在线")

    await asyncio.sleep(plan.read_delay)
    await runner.mark_read(tg_id)

    ids: list[int] = []
    for idx, part in enumerate(plan.parts):
        try:
            assert runner.client
            async with runner.client.action(await runner._peer(tg_id), "typing"):
                await asyncio.sleep(plan.typing[idx])
            if idx == len(plan.parts) - 1 and plan.use_voice and voice_path:
                mid = await runner.send_voice(tg_id, voice_path, voice_duration)
            else:
                mid = await runner.send_text(tg_id, part)
            if mid:
                ids.append(mid)
        except FloodWaitError as e:
            await RateLimiter(_StubAccount(account_id)).set_floodwait(int(e.seconds))
            log.warning("FloodWait %s 秒 (account %s)", e.seconds, account_id)
            raise
        except RPCError as e:
            log.warning("发送失败 account=%s: %s", account_id, e)
            raise
        if idx < len(plan.gaps):
            await asyncio.sleep(plan.gaps[idx])
    return ids


class _StubAccount:
    def __init__(self, account_id: int) -> None:
        self.id = account_id
        self.enabled = True
        self.ai_enabled = True
        self.rate_limits: dict = {}
