"""后台作业：风格重建、画像冷启动、主动会话任务。"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..db import SessionLocal
from ..models import (
    Account,
    Contact,
    Message,
    ProactiveTarget,
    ProactiveTask,
    StyleSample,
)
from ..core import lang as langmod
from ..core import memory, profile as profile_mod, style as style_mod
from ..core.llm import LLMError, get_client, log_usage
from ..core.persona import build_opening_prompt, build_system_prompt
from ..core.ratelimit import RateLimiter
from ..core.typing import in_active_hours, plan_send
from ..tg.handlers import _mark_ai_sent, _pick_persona
from ..tg.manager import human_send

log = logging.getLogger("workers")


# ---------- 风格 ----------
async def rebuild_style_job(account_id: int) -> dict:
    async with SessionLocal() as db:
        prof = await style_mod.rebuild_profile(db, account_id)
        await db.commit()
        return {"account_id": account_id, "samples": prof.sample_count, "summary": prof.summary}


async def import_style_job(account_id: int, texts: list[str]) -> dict:
    async with SessionLocal() as db:
        n = await style_mod.import_samples(db, account_id, texts)
        prof = await style_mod.rebuild_profile(db, account_id)
        await db.commit()
        return {"imported": n, "summary": prof.summary}


async def pull_history_job(account_id: int, limit: int = 300) -> dict:
    """从 Telegram 拉本人最近发出的消息，作为风格样本。"""
    from ..tg.manager import manager

    runner = manager.runners.get(account_id)
    if not runner or not runner.client:
        raise RuntimeError("账号未在线，先启动账号")
    me = await runner.client.get_me()
    texts = await runner.read_history(me.id, limit=limit)
    async with SessionLocal() as db:
        n = await style_mod.import_samples(db, account_id, texts)
        prof = await style_mod.rebuild_profile(db, account_id)
        await db.commit()
        return {"pulled": n, "summary": prof.summary}


# ---------- 画像 ----------
async def cold_start_job(contact_id: int) -> dict:
    async with SessionLocal() as db:
        contact = await db.get(Contact, contact_id)
        if not contact:
            raise RuntimeError("联系人不存在")
        llm, _ = await get_client(db)
        res = await profile_mod.cold_start(llm, db, contact=contact)
        await db.commit()
        return {"contact_id": contact_id, "profile": res}


# ---------- 主动会话 ----------
async def _opening_for(
    db, *, task: ProactiveTask, contact: Contact, persona, used: list[str], lang: str
) -> str:
    llm, _ = await get_client(db)
    facts = await memory.retrieve_facts(db, account_id=task.account_id, contact_id=contact.id, query=" ", k=6)
    style = (
        await db.execute(select(style_mod.StyleProfile).where(style_mod.StyleProfile.account_id == task.account_id))
    ).scalar_one_or_none()
    few = await style_mod.pick_few_shots(db, account_id=task.account_id, query=" ", lang=lang, k=5)
    system = build_system_prompt(
        persona=persona,
        account=await db.get(Account, task.account_id),
        contact=contact,
        lang=lang,
        lang_mode="follow",
        facts=facts,
        style=style,
        few_shots=few,
        stranger=True,
    )
    msgs = build_opening_prompt(
        system=system,
        goal=task.goal,
        contact_name=contact.first_name or "对方",
        used=used,
    )
    text, usage = await llm.chat(msgs, temperature=1.0)
    await log_usage(db, account_id=task.account_id, kind="llm", usage=usage)
    return langmod.apply_language(text.strip(), lang)


async def run_proactive_task(task_id: int, max_sends: int | None = None) -> dict:
    """执行一次主动任务：按 daily_limit / 间隔 / 时段限额发开场白。"""
    sent = 0
    errors: list[str] = []
    async with SessionLocal() as db:
        task = await db.get(ProactiveTask, task_id)
        if not task or task.status != "active":
            return {"sent": 0, "msg": "任务不存在或未启用"}
        acc = await db.get(Account, task.account_id)
        if not acc or not acc.proactive_enabled or not acc.ai_enabled:
            return {"sent": 0, "msg": "账号主动发送已关闭"}

        limiter = RateLimiter(acc)
        cap_today = limiter.proactive_daily_cap()
        if cap_today <= 0:
            return {"sent": 0, "msg": "仍在预热静默期，暂不主动发送"}

        persona = await _pick_persona(db, acc, (await db.execute(select(Contact).limit(1))).scalar_one_or_none()) if False else None
        if task.persona_id:
            from ..models import Persona

            persona = await db.get(Persona, task.persona_id)
        if not persona and acc.persona_id:
            from ..models import Persona

            persona = await db.get(Persona, acc.persona_id)
        if not persona:
            return {"sent": 0, "msg": "没有可用人设"}

        now = datetime.now(timezone.utc)
        if not in_active_hours(persona.timezone, {"start": task.window_start, "end": task.window_end}, now):
            return {"sent": 0, "msg": "不在发送时段"}

        # 今日已发数
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_sent = (
            await db.execute(
                select(func.count(ProactiveTarget.id)).where(
                    ProactiveTarget.task_id == task.id,
                    ProactiveTarget.status == "sent",
                    ProactiveTarget.sent_at >= day_start,
                )
            )
        ).scalar() or 0
        quota = max(0, min(task.daily_limit, cap_today) - int(today_sent))
        if max_sends is not None:
            quota = min(quota, max_sends)
        if quota <= 0:
            return {"sent": 0, "msg": "今日额度已用完"}

        targets = (
            await db.execute(
                select(ProactiveTarget)
                .where(ProactiveTarget.task_id == task.id, ProactiveTarget.status == "pending")
                .limit(quota * 3)
            )
        ).scalars().all()
        if not targets:
            return {"sent": 0, "msg": "没有待发送对象"}

        used = [
            r[0]
            for r in (
                await db.execute(select(ProactiveTarget.opening).where(ProactiveTarget.task_id == task.id).limit(200))
            ).all()
            if r[0]
        ]
        target_ids = [t.contact_id for t in targets]

    # 逐条发送，条间随机间隔（错峰）
    for tid in target_ids[:quota]:
        try:
            async with SessionLocal() as db:
                contact = await db.get(Contact, tid)
                target = (
                    await db.execute(
                        select(ProactiveTarget).where(
                            ProactiveTarget.task_id == task_id, ProactiveTarget.contact_id == tid
                        )
                    )
                ).scalar_one_or_none()
                if not contact or not target or target.status != "pending":
                    continue
                if contact.blacklist or not contact.ai_enabled:
                    target.status = "failed"
                    target.error = "联系人已停用"
                    await db.commit()
                    continue
                acc = await db.get(Account, task.account_id)
                ok, reason = await RateLimiter(acc).check(proactive=True)
                if not ok:
                    errors.append(reason)
                    break

                lang = langmod.detect_lang(contact.lang or "") or persona.default_language
                opening = await _opening_for(
                    db, task=task, contact=contact, persona=persona, used=used, lang=lang
                )
                await db.commit()

            if not opening:
                continue
            plan = plan_send(
                opening,
                persona_paragraph=persona.paragraph_habit,
                is_stranger=True,
                voice_ratio=0,
            )
            ids = await human_send(
                account_id=task.account_id, tg_id=contact.tg_id, text=opening, plan=plan
            )
            for mid in ids:
                _mark_ai_sent(task.account_id, mid)

            async with SessionLocal() as db:
                target = (
                    await db.execute(
                        select(ProactiveTarget).where(
                            ProactiveTarget.task_id == task_id, ProactiveTarget.contact_id == tid
                        )
                    )
                ).scalar_one_or_none()
                if target:
                    target.status = "sent"
                    target.opening = opening
                    target.sent_at = datetime.now(timezone.utc)
                contact = await db.get(Contact, tid)
                if contact:
                    contact.last_msg_at = datetime.now(timezone.utc)
                db.add(
                    Message(
                        account_id=task.account_id,
                        contact_id=tid,
                        direction="out",
                        source="ai",
                        text=opening,
                        lang=lang,
                        meta={"proactive": True, "task_id": task_id, "persona_id": persona.id},
                    )
                )
                t = await db.get(ProactiveTask, task_id)
                if t:
                    t.created_count += 1
                    t.last_run_at = datetime.now(timezone.utc)
                acc2 = await db.get(Account, task.account_id)
                await RateLimiter(acc2).consume(proactive=True)
                await db.commit()
            used.append(opening)
            sent += 1
        except Exception as e:
            log.warning("主动发送失败 contact=%s: %s", tid, e)
            errors.append(f"{tid}: {e}")
            try:
                async with SessionLocal() as db:
                    target = (
                        await db.execute(
                            select(ProactiveTarget).where(
                                ProactiveTarget.task_id == task_id, ProactiveTarget.contact_id == tid
                            )
                        )
                    ).scalar_one_or_none()
                    if target:
                        target.status = "failed"
                        target.error = str(e)[:300]
                        await db.commit()
            except Exception:
                pass

        # 条间错峰
        async with SessionLocal() as db:
            task = await db.get(ProactiveTask, task_id)
        gap = random.uniform(task.interval_min, task.interval_max) if task else 300
        if sent < len(target_ids[:quota]):
            await asyncio.sleep(min(gap, 900))

    return {"sent": sent, "errors": errors[:5]}


def run_proactive_task_sync(task_id: int) -> dict:
    return asyncio.run(run_proactive_task(task_id))
