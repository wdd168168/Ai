"""兴趣画像：每个联系人自动生成 兴趣 TOP5 / 回避话题 / 情绪基线 / 亲密度 / 未完成话题 / 关键事实。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, Message
from .llm import LLMClient

PROFILE_PROMPT = """你是对话分析师。根据这个人和我的聊天，更新对他的画像。

输出 JSON：
{
  "interests": [{"topic":"健身","score":0.9,"evidence":"连续聊了健身和增肌"}],   // 最多 5 个，score 0-1
  "avoid_topics": ["前任"],        // 他明显不想聊的
  "emotion_baseline": "positive|neutral|low|anxious",   // 最近情绪基调
  "intimacy": 55,                  // 0-100，关系亲密度（保守估计，普通聊天 20-45）
  "unfinished_topics": ["他说要发我旅行照片但还没发"],    // 悬着没结束的话题，最多 3 个
  "key_facts": ["在金边做手机配件生意"]                 // 关键事实短句，最多 5 个
}

规则：只依据对话内容，不要编。没提到的字段保持空数组或原值。"""


async def update_profile(
    llm: LLMClient,
    db: AsyncSession,
    *,
    contact: Contact,
    history: list[tuple[str, str]],
    known_profile: dict | None = None,
) -> dict:
    if len(history) < 4:
        return {}
    dialog = "\n".join(f"{'我' if r == 'out' else '对方'}：{t}" for r, t in history[-30:])
    known = known_profile or {
        "interests": contact.interests,
        "avoid_topics": contact.avoid_topics,
        "emotion_baseline": contact.emotion_baseline,
        "intimacy": contact.intimacy,
        "unfinished_topics": contact.unfinished_topics,
        "key_facts": contact.key_facts,
    }
    data, _ = await llm.chat_json(
        [
            {"role": "system", "content": PROFILE_PROMPT},
            {
                "role": "user",
                "content": f"已有画像：{known}\n\n对话：\n{dialog}",
            },
        ],
        temperature=0.2,
        max_tokens=800,
    )
    if not isinstance(data, dict):
        return {}

    if isinstance(data.get("interests"), list):
        items = []
        for it in data["interests"][:5]:
            if isinstance(it, dict) and it.get("topic"):
                items.append(
                    {
                        "topic": str(it["topic"])[:40],
                        "score": float(it.get("score", 0.5) or 0.5),
                        "evidence": str(it.get("evidence", ""))[:120],
                    }
                )
        contact.interests = items
    if isinstance(data.get("avoid_topics"), list):
        contact.avoid_topics = [str(x)[:40] for x in data["avoid_topics"][:5] if x]
    if data.get("emotion_baseline") in ("positive", "neutral", "low", "anxious"):
        contact.emotion_baseline = data["emotion_baseline"]
    if isinstance(data.get("intimacy"), (int, float)):
        target = max(0, min(100, int(data["intimacy"])))
        # 平滑，避免一轮暴涨
        contact.intimacy = int(contact.intimacy * 0.6 + target * 0.4)
    if isinstance(data.get("unfinished_topics"), list):
        contact.unfinished_topics = [str(x)[:80] for x in data["unfinished_topics"][:3] if x]
    if isinstance(data.get("key_facts"), list):
        contact.key_facts = [str(x)[:80] for x in data["key_facts"][:5] if x]
    contact.profile_updated_at = datetime.now(timezone.utc)
    await db.flush()
    return data


async def cold_start(
    llm: LLMClient, db: AsyncSession, *, contact: Contact, batch: int = 30
) -> dict:
    """有历史记录时批量冷启动抽取（分页喂，避免一次塞爆）。"""
    rows = (
        await db.execute(
            select(Message)
            .where(Message.account_id == contact.account_id, Message.contact_id == contact.id)
            .order_by(Message.created_at.asc())
            .limit(batch * 4)
        )
    ).scalars().all()
    history = [("out" if m.direction == "out" else "in", m.text) for m in rows]
    merged: dict = {}
    for i in range(0, len(history), batch):
        chunk = history[i : i + batch]
        res = await update_profile(llm, db, contact=contact, history=chunk, known_profile=merged or None)
        if res:
            merged.update(res)
    return merged
