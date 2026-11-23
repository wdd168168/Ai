"""上下文引擎：短期对话 + 长期结构化事实库，按联系人隔离，绝不串台。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, MemoryFact, Message
from .timeutil import as_utc
from .llm import LLMClient

SHORT_TERM_N = 20

FACT_CATEGORIES = ("identity", "work", "family", "preference", "appointment", "todo", "fact")

EXTRACT_PROMPT = """你是信息抽取器。从下面的对话里抽取**关于对方**的、以后聊天用得上的长期信息。

只抽这几类：
- identity：身份/住址/年龄/学历等稳定信息
- work：工作、公司、项目、收入相关
- family：家人、伴侣、孩子
- preference：喜好、厌恶、习惯、作息
- appointment：约定的时间地点（如"下周三去曼谷出差"）
- todo：对方说要去做但还没做的事
- fact：其它值得记住的事实

规则：
1. 只抽对方说的或明确确认的，不要猜。
2. 每条一句话，中文陈述，带具体信息（时间/地点/人名要写清）。
3. 已经在"已知事实"里的不要重复抽。
4. 没有新信息就返回空数组。
5. 最多 6 条。

输出 JSON：{"facts":[{"category":"appointment","content":"11月25日（下周三）去曼谷出差","weight":1.2,"due_at":"2026-11-25"}]}
due_at 只在 appointment/todo 有明确日期时填 YYYY-MM-DD，否则 null。"""


def _kw(text: str) -> set[str]:
    """粗粒度关键词：中文双字 + 拉丁词。"""
    t = text.lower()
    words = set(re.findall(r"[a-z]{3,}", t))
    han = re.findall(r"[\u4e00-\u9fff]", t)
    for i in range(len(han) - 1):
        words.add(han[i] + han[i + 1])
    return words


async def get_history(
    db: AsyncSession, account_id: int, contact_id: int, limit: int = SHORT_TERM_N
) -> list[tuple[str, str]]:
    rows = (
        await db.execute(
            select(Message)
            .where(Message.account_id == account_id, Message.contact_id == contact_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [("out" if m.direction == "out" else "in", m.text) for m in reversed(rows)]


async def retrieve_facts(
    db: AsyncSession,
    *,
    account_id: int,
    contact_id: int,
    query: str,
    k: int = 10,
    now: datetime | None = None,
) -> list[MemoryFact]:
    """相关性检索：关键词重合 + 权重 + 时间衰减。联系人维度硬隔离。"""
    now = now or datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(MemoryFact).where(
                MemoryFact.account_id == account_id,
                MemoryFact.contact_id == contact_id,
            )
        )
    ).scalars().all()

    qk = _kw(query)
    scored: list[tuple[float, MemoryFact]] = []
    for f in rows:
        if f.expires_at and as_utc(f.expires_at) < now:
            continue
        fk = _kw(f.content)
        overlap = len(qk & fk)
        score = overlap * 2.0 + f.weight
        age_days = max(0.0, (now - (as_utc(f.created_at) or now)).total_seconds() / 86400)
        if f.category in ("appointment", "todo"):
            score += 1.5
            if f.due_at and as_utc(f.due_at) >= now:
                score += 2.0
        score -= min(age_days * 0.02, 1.0)
        scored.append((score, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:k]]


async def save_facts(
    db: AsyncSession,
    *,
    account_id: int,
    contact_id: int,
    facts: list[dict],
    source_msg_id: int | None = None,
) -> list[MemoryFact]:
    existing = (
        await db.execute(
            select(MemoryFact).where(
                MemoryFact.account_id == account_id, MemoryFact.contact_id == contact_id
            )
        )
    ).scalars().all()
    saved: list[MemoryFact] = []
    for raw in facts[:8]:
        content = (raw.get("content") or "").strip()
        if not content or len(content) > 300:
            continue
        cat = raw.get("category") if raw.get("category") in FACT_CATEGORIES else "fact"
        # 去重：同义/包含关系视为同一条，更新权重
        dup = next((e for e in existing if content in e.content or e.content in content), None)
        due = None
        if raw.get("due_at"):
            try:
                due = datetime.fromisoformat(str(raw["due_at"])).replace(tzinfo=timezone.utc)
            except Exception:
                due = None
        if dup:
            dup.weight = min(5.0, dup.weight + 0.4)
            dup.content = content if len(content) > len(dup.content) else dup.content
            if due:
                dup.due_at = due
            saved.append(dup)
        else:
            f = MemoryFact(
                account_id=account_id,
                contact_id=contact_id,
                category=cat,
                content=content,
                weight=float(raw.get("weight", 1.0) or 1.0),
                source_msg_id=source_msg_id,
                due_at=due,
            )
            db.add(f)
            existing.append(f)
            saved.append(f)
    await db.flush()
    return saved


async def extract_facts(
    llm: LLMClient,
    *,
    db: AsyncSession,
    account_id: int,
    contact_id: int,
    history: list[tuple[str, str]],
    known: list[MemoryFact],
    source_msg_id: int | None = None,
) -> list[MemoryFact]:
    if not history:
        return []
    dialog = "\n".join(f"{'我' if r == 'out' else '对方'}：{t}" for r, t in history[-14:])
    known_text = "\n".join(f"- {f.content}" for f in known[:20]) or "- （空）"
    data, _ = await llm.chat_json(
        [
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": f"已知事实：\n{known_text}\n\n对话：\n{dialog}"},
        ]
    )
    facts = data.get("facts", []) if isinstance(data, dict) else []
    return await save_facts(
        db, account_id=account_id, contact_id=contact_id, facts=facts, source_msg_id=source_msg_id
    )


async def clear_contact_memory(db: AsyncSession, account_id: int, contact_id: int) -> int:
    res = await db.execute(
        delete(MemoryFact).where(
            MemoryFact.account_id == account_id, MemoryFact.contact_id == contact_id
        )
    )
    await db.execute(
        delete(Message).where(Message.account_id == account_id, Message.contact_id == contact_id)
    )
    return res.rowcount or 0


async def due_soon(db: AsyncSession, contact_id: int, days: int = 3) -> list[MemoryFact]:
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(MemoryFact).where(
                MemoryFact.contact_id == contact_id,
                MemoryFact.due_at.is_not(None),
                MemoryFact.due_at <= now + timedelta(days=days),
                MemoryFact.due_at >= now - timedelta(days=1),
            )
        )
    ).scalars().all()
    return list(rows)
