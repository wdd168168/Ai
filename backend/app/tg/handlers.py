"""对话编排：收消息 → 决策 → 生成 → 拟人化发送 → 落库 → 异步更新画像/记忆。"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import Account, Contact, Message, Persona, PersonaRule, Setting
from ..core import lang as langmod
from ..core import memory, profile as profile_mod, style as style_mod, tts as ttsmod
from ..core.llm import LLMError, get_client, log_usage
from ..core.persona import build_messages, build_system_prompt
from ..core.ratelimit import RateLimiter
from ..core.timeutil import as_utc
from ..core.typing import in_active_hours, next_active_time, plan_send
from .manager import human_send, manager

log = logging.getLogger("tg.handlers")

# 记忆/画像抽取这类后台活很吃额度：同一个联系人最小间隔内只跑一次
_PP_LAST: dict[int, float] = {}
PP_MIN_INTERVAL = int(os.getenv("POST_PROCESS_INTERVAL", "600"))

# AI 自己发出的消息 id，用于区分"本人手动回复"
AI_SENT: dict[tuple[int, int], float] = {}
_SENT_TTL = 3600

DEFAULT_CHAT_CFG = {
    "lang_mode": "follow",          # follow | fixed | persona | mix
    "manual_yield_minutes": 20,     # 本人手动回复后 AI 让路多久
    "stranger_first_delay": True,
    "reply_in_offhours": False,
}


async def get_chat_cfg(db) -> dict:
    row = await db.get(Setting, "chat_config")
    cfg = dict(DEFAULT_CHAT_CFG)
    if row and isinstance(row.value, dict):
        cfg.update(row.value)
    return cfg


def _mark_ai_sent(account_id: int, msg_id: int) -> None:
    now = time.time()
    AI_SENT[(account_id, msg_id)] = now
    for k, ts in list(AI_SENT.items()):
        if now - ts > _SENT_TTL:
            AI_SENT.pop(k, None)


async def _get_or_create_contact(db, account_id: int, tg_id: int, sender) -> Contact:
    contact = (
        await db.execute(
            select(Contact).where(Contact.account_id == account_id, Contact.tg_id == tg_id)
        )
    ).scalar_one_or_none()
    if contact:
        if sender:
            contact.first_name = getattr(sender, "first_name", None) or contact.first_name
            contact.last_name = getattr(sender, "last_name", None) or contact.last_name
            contact.username = getattr(sender, "username", None) or contact.username
        return contact
    contact = Contact(
        account_id=account_id,
        tg_id=tg_id,
        first_name=getattr(sender, "first_name", "") or "",
        last_name=getattr(sender, "last_name", "") or "",
        username=getattr(sender, "username", None),
    )
    db.add(contact)
    await db.flush()
    return contact


async def _pick_persona(db, acc: Account, contact: Contact) -> Persona | None:
    now_local = datetime.now(timezone.utc)
    rules = (
        await db.execute(
            select(PersonaRule).where(
                PersonaRule.account_id == acc.id, PersonaRule.enabled == True  # noqa: E712
            ).order_by(PersonaRule.priority.desc())
        )
    ).scalars().all()
    hhmm = now_local.strftime("%H:%M")
    for r in rules:
        if r.contact_id and r.contact_id != contact.id:
            continue
        if r.time_start <= r.time_end:
            if not (r.time_start <= hhmm <= r.time_end):
                continue
        else:
            if not (hhmm >= r.time_start or hhmm <= r.time_end):
                continue
        p = await db.get(Persona, r.persona_id)
        if p:
            return p
    if acc.persona_id:
        return await db.get(Persona, acc.persona_id)
    return (await db.execute(select(Persona).limit(1))).scalar_one_or_none()


async def _resolve_lang(db, acc: Account, contact: Contact, persona: Persona | None, incoming: str) -> tuple[str, str]:
    cfg = await get_chat_cfg(db)
    mode = cfg.get("lang_mode", "follow")
    detected = langmod.detect_lang(incoming)
    if mode == "fixed":
        row = await db.get(Setting, "chat_config")
        fixed = (row.value or {}).get("fixed_lang", "zh-CN") if row else "zh-CN"
        return fixed, "fixed"
    if mode == "persona" and persona:
        return persona.default_language, "fixed"
    if mode == "mix" and persona:
        return (detected or persona.default_language), "follow"
    return (detected or (persona.default_language if persona else "zh-CN")), "follow"


async def generate_reply(account_id: int, contact_id: int, incoming: str) -> tuple[str, str, dict]:
    """核心生成：返回 (文本, 语言, 元信息)。不负责发送。"""
    async with SessionLocal() as db:
        acc = await db.get(Account, account_id)
        contact = await db.get(Contact, contact_id)
        if not acc or not contact:
            raise RuntimeError("账号或联系人不存在")
        persona = await _pick_persona(db, acc, contact)
        if not persona:
            raise RuntimeError("没有可用人设，请先在后台创建人设并绑定账号")

        lang, mode = await _resolve_lang(db, acc, contact, persona, incoming)
        facts = await memory.retrieve_facts(
            db, account_id=account_id, contact_id=contact_id, query=incoming, k=10
        )
        style = (
            await db.execute(select(style_mod.StyleProfile).where(style_mod.StyleProfile.account_id == account_id))
        ).scalar_one_or_none()
        few = await style_mod.pick_few_shots(db, account_id=account_id, query=incoming, lang=lang, k=8)
        history = await memory.get_history(db, account_id, contact_id, limit=20)
        stranger = len(history) <= 2

        system = build_system_prompt(
            persona=persona,
            account=acc,
            contact=contact,
            lang=lang,
            lang_mode=mode,
            facts=facts,
            style=style,
            few_shots=few,
            stranger=stranger,
        )
        # 历史里如果最后一条就是本轮这条 incoming，避免重复喂给模型
        hist = history
        if hist and hist[-1][0] == "in" and hist[-1][1].strip() == incoming.strip():
            hist = hist[:-1]
        msgs = build_messages(
            system=system, history=hist, incoming=incoming, contact_name=contact.first_name
        )

        llm, _cfg = await get_client(db)
        text, usage = await llm.chat(msgs)
        if not text.strip():
            # 推理型模型偶尔把额度全花在思考上，正文空；加大额度重试一次
            log.info("模型返回空正文，加大额度重试")
            text, usage = await llm.chat(msgs, max_tokens=int((_cfg.max_tokens or 700) * 2))
        if not text.strip():
            raise LLMError("模型返回空内容")
        await log_usage(db, account_id=account_id, kind="llm", usage=usage)
        await db.commit()

        text = langmod.apply_language(text, lang)
        issues = langmod.check_mixed_script(text) if lang in ("zh-TW", "zh-CN") else []
        meta = {
            "persona_id": persona.id,
            "persona_name": persona.name,
            "lang": lang,
            "lang_mode": mode,
            "memory_used": [f.content for f in facts[:6]],
            "style_refs": few[:5],
            "mixed_script_issues": issues,
            "stranger": stranger,
            "voice_ratio": persona.voice_ratio,
            "voice_id": persona.voice_id,
            "gender": persona.gender,
            "paragraph": persona.paragraph_habit,
            "timezone": persona.timezone,
            "active_hours": persona.active_hours,
        }
        return text, lang, meta


async def _send_reply(account_id: int, contact_id: int, text: str, lang: str, meta: dict) -> None:
    """拟人化发送 + 落库。"""
    rng = random.Random(f"{account_id}-{contact_id}-{int(time.time())}")
    plan = plan_send(
        text,
        persona_paragraph=meta.get("paragraph", "拆条"),
        is_stranger=meta.get("stranger", False),
        voice_ratio=int(meta.get("voice_ratio", 0)),
        scene=meta.get("scene", ""),
        rng=rng,
    )
    if not plan.parts:
        return

    voice_path, voice_dur = "", 0.0
    if plan.use_voice:
        try:
            voice_path, voice_dur = await ttsmod.synthesize(
                plan.parts[-1], lang=lang, gender=meta.get("gender", "female"), voice=meta.get("voice_id", "")
            )
        except Exception as e:
            log.warning("语音合成失败，退回文字: %s", e)
            plan.use_voice = False

    ids = await human_send(
        account_id=account_id,
        tg_id=await _tg_id(contact_id),
        text=text,
        plan=plan,
        voice_path=voice_path,
        voice_duration=voice_dur,
    )
    for mid in ids:
        _mark_ai_sent(account_id, mid)

    if voice_path:
        try:
            os.remove(voice_path)
        except OSError:
            pass

    async with SessionLocal() as db:
        contact = await db.get(Contact, contact_id)
        for i, part in enumerate(plan.parts):
            is_voice_last = i == len(plan.parts) - 1 and plan.use_voice
            db.add(
                Message(
                    account_id=account_id,
                    contact_id=contact_id,
                    tg_msg_id=ids[i] if i < len(ids) else None,
                    direction="out",
                    source="ai",
                    text=part,
                    lang=lang,
                    msg_type="voice" if is_voice_last else "text",
                    meta={**meta, "typing_seconds": plan.typing[i], "part": i},
                )
            )
        if contact:
            contact.last_msg_at = datetime.now(timezone.utc)
        acc = await db.get(Account, account_id)
        if acc:
            await RateLimiter(acc).consume()
        await db.commit()


async def _tg_id(contact_id: int) -> int:
    async with SessionLocal() as db:
        c = await db.get(Contact, contact_id)
        return c.tg_id if c else 0


async def _post_process(account_id: int, contact_id: int) -> None:
    """会话结束后异步更新：记忆抽取 + 兴趣画像（不阻塞回复）。"""
    now_ts = time.time()
    if now_ts - _PP_LAST.get(contact_id, 0) < PP_MIN_INTERVAL:
        return
    _PP_LAST[contact_id] = now_ts
    try:
        async with SessionLocal() as db:
            acc = await db.get(Account, account_id)
            contact = await db.get(Contact, contact_id)
            if not acc or not contact:
                return
            llm, _ = await get_client(db)
            history = await memory.get_history(db, account_id, contact_id, limit=16)
            known = await memory.retrieve_facts(
                db, account_id=account_id, contact_id=contact_id, query=" ".join(t for _, t in history), k=20
            )
            await memory.extract_facts(
                llm, db=db, account_id=account_id, contact_id=contact_id, history=history, known=known
            )
            await profile_mod.update_profile(llm, db, contact=contact, history=history)
            await db.commit()
    except Exception as e:
        log.info("后处理跳过: %s", e)


async def handle_message(account_id: int, contact_id: int, incoming: str, scene: str = "") -> None:
    """外部（含主动任务回复、控制 bot）也可调用。"""
    try:
        text, lang, meta = await generate_reply(account_id, contact_id, incoming)
        if scene:
            meta["scene"] = scene
        await _send_reply(account_id, contact_id, text, lang, meta)
        asyncio.create_task(_post_process(account_id, contact_id))
    except LLMError as e:
        log.warning("模型不可用，跳过回复 account=%s: %s", account_id, e)
        async with SessionLocal() as db:
            acc = await db.get(Account, account_id)
            if acc:
                acc.last_error = f"模型错误: {e}"[:500]
                await db.commit()
    except Exception as e:
        log.exception("回复失败 account=%s contact=%s: %s", account_id, contact_id, e)


# ---------------- Telegram 事件 ----------------
async def on_outgoing(account_id: int, event) -> None:
    """本人手动回复 → AI 让路。"""
    try:
        if not event.is_private or not event.message:
            return
        mid = event.message.id
        if (account_id, mid) in AI_SENT:
            return
        if not event.message.message:
            return
        async with SessionLocal() as db:
            cfg = await get_chat_cfg(db)
            contact = await _get_or_create_contact(db, account_id, event.chat_id, None)
            contact.mute_until = datetime.now(timezone.utc) + timedelta(
                minutes=int(cfg.get("manual_yield_minutes", 20))
            )
            db.add(
                Message(
                    account_id=account_id,
                    contact_id=contact.id,
                    tg_msg_id=mid,
                    direction="out",
                    source="manual",
                    text=event.message.message,
                    lang=langmod.detect_lang(event.message.message),
                )
            )
            await db.commit()
            log.info("检测到手动回复，AI 让路 20 分钟 contact=%s", contact.id)
    except Exception as e:
        log.warning("outgoing 处理异常: %s", e)


async def on_incoming(account_id: int, event) -> None:
    try:
        if not event.is_private:
            return
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False) or getattr(sender, "is_self", False):
            return
        text = event.raw_text or ""
        msg_type = "text"
        media_path = ""

        async with SessionLocal() as db:
            acc = await db.get(Account, account_id)
            if not acc:
                return
            contact = await _get_or_create_contact(db, account_id, event.chat_id, sender)
            contact.last_msg_at = datetime.now(timezone.utc)

            if event.message.voice or event.message.audio:
                msg_type = "voice"
                try:
                    in_dir = os.path.join(settings.MEDIA_DIR, "incoming")
                    os.makedirs(in_dir, exist_ok=True)
                    ext = ".ogg" if event.message.voice else ".mp3"
                    fname = f"in_{account_id}_{event.message.id}{ext}"
                    path = await event.download_media(file=os.path.join(in_dir, fname))
                    media_path = path or ""
                    from ..core import asr

                    text = await asr.transcribe(media_path, contact.lang or "")
                    if not text:
                        text = "[语音]"
                except Exception as e:
                    log.warning("语音转写失败: %s", e)
                    text = "[语音]"

            db.add(
                Message(
                    account_id=account_id,
                    contact_id=contact.id,
                    tg_msg_id=event.message.id,
                    direction="in",
                    source="contact",
                    text=text,
                    lang=langmod.detect_lang(text),
                    msg_type=msg_type,
                    media_path=media_path,
                )
            )
            await db.commit()

            if not text.strip():
                return
            if contact.blacklist or not contact.ai_enabled:
                return
            if contact.mute_until and as_utc(contact.mute_until) > datetime.now(timezone.utc):
                return
            if not acc.enabled or not acc.ai_enabled or not acc.auto_reply:
                return

            # 作息：不在活跃时段，按配置决定是否延后
            persona = await _pick_persona(db, acc, contact)
            tz = persona.timezone if persona else "UTC"
            hours = persona.active_hours if persona else {"start": "09:00", "end": "23:00"}
            offhours = not in_active_hours(tz, hours)
            cfg = await get_chat_cfg(db)
            if offhours and not cfg.get("reply_in_offhours", False):
                target = next_active_time(tz, hours)
                delay = max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
                if delay > 3600 * 10:  # 太久就不排了，避免堆积
                    return
                log.info("非活跃时段，延后 %s 秒回复", int(delay))
                asyncio.create_task(_delayed_reply(account_id, contact.id, text, delay))
                return

            # 限速
            ok, reason = await RateLimiter(acc).check()
            if not ok:
                log.info("限速跳过: %s", reason)
                return

            cid = contact.id

        await handle_message(account_id, cid, text)
    except Exception as e:
        log.exception("incoming 处理异常: %s", e)


async def _delayed_reply(account_id: int, contact_id: int, text: str, delay: float) -> None:
    await asyncio.sleep(delay)
    async with SessionLocal() as db:
        acc = await db.get(Account, account_id)
        if not acc or not acc.enabled or not acc.ai_enabled:
            return
    await handle_message(account_id, contact_id, text)
