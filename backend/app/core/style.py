"""风格学习：从本人历史消息里抽出结构化风格档案 + 动态 few-shot 检索。"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import StyleProfile, StyleSample
from .timeutil import as_utc

STOPWORDS = set(
    "的 了 是 我 你 他 她 它 在 有 和 就 都 也 不 吗 呢 啊 吧 呀 哦 嗯 这 那 个 上 下 去 来 说 要 会 得 到 很 太 又 再 还 把 被 给 对 让 着 过 着 一 二 三 什么 怎么 这个 那个 现在 今天 明天 哈哈 哈哈哈".split()
)
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2b00-\u2bff]"
)
ADDRESS_CANDIDATES = ["宝贝", "亲爱的", "老公", "老婆", "哥", "姐", "弟弟", "妹妹", "小可爱", "宝", "兄弟", "老板"]


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[。！？!?…~\n]+", text) if s.strip()]


def extract_catchphrases(texts: list[str], top: int = 8) -> list[str]:
    counter: Counter[str] = Counter()
    for t in texts:
        clean = EMOJI_RE.sub(" ", t)
        for n in (2, 3):
            for i in range(len(clean) - n + 1):
                gram = clean[i : i + n]
                if not re.fullmatch(r"[\u4e00-\u9fff]+", gram):
                    continue
                if gram in STOPWORDS or any(w in STOPWORDS for w in gram):
                    continue
                counter[gram] += 1
    # 出现 ≥3 次才算口头禅；去包含关系
    cands = [(g, c) for g, c in counter.most_common(40) if c >= 3]
    picked: list[str] = []
    for g, c in cands:
        if any(g in p or p in g for p in picked):
            continue
        picked.append(g)
        if len(picked) >= top:
            break
    return picked


def analyze(
    texts: list[str], times: list[datetime] | None = None
) -> dict:
    """纯本地统计，不依赖模型，结果可复现。"""
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return {
            "sample_count": 0,
            "avg_sentence_len": 0.0,
            "paragraph_ratio": 0.0,
            "emoji_rate": 0.0,
            "catchphrases": [],
            "punctuation": {},
            "address_style": {},
            "active_hours": {},
            "summary": "",
        }
    sent_lens: list[int] = []
    for t in texts:
        for s in split_sentences(t):
            sent_lens.append(len(s))
    avg_len = sum(sent_lens) / max(1, len(sent_lens))

    multiline = sum(1 for t in texts if "\n" in t.strip())
    emoji_msgs = sum(1 for t in texts if EMOJI_RE.search(t))

    punc_counter = Counter()
    for t in texts:
        for ch in t:
            if ch in "，。！？!?…~～、；：":
                punc_counter[ch] += 1
    top_punc = [f"{c}({n})" for c, n in punc_counter.most_common(4)]

    addr = Counter()
    for t in texts:
        for a in ADDRESS_CANDIDATES:
            if a in t:
                addr[a] += 1

    hours: Counter[int] = Counter()
    if times:
        for dt in times:
            local = dt.astimezone(timezone.utc)
            hours[local.hour] += 1

    # 问句率 / 语气词率
    q = sum(1 for t in texts if re.search(r"[？?]|吗|呢|嘛", t)) / len(texts)
    tone_words = sum(1 for t in texts if re.search(r"[啊呀吧啦哈哦嗯诶]", t)) / len(texts)

    summary = (
        f"平均每句 {avg_len:.1f} 字，{multiline/len(texts)*100:.0f}% 的消息分多段落发送，"
        f"{emoji_msgs/len(texts)*100:.0f}% 带 emoji，{q*100:.0f}% 会反问，{tone_words*100:.0f}% 带语气词。"
    )

    return {
        "sample_count": len(texts),
        "avg_sentence_len": round(avg_len, 1),
        "paragraph_ratio": round(multiline / len(texts), 3),
        "emoji_rate": round(emoji_msgs / len(texts), 3),
        "catchphrases": extract_catchphrases(texts),
        "punctuation": {"top": top_punc, "raw": dict(punc_counter)},
        "address_style": {"calls": [a for a, _ in addr.most_common(3)]},
        "active_hours": {"peak": [h for h, _ in hours.most_common(4)]} if hours else {},
        "summary": summary,
    }


async def rebuild_profile(db: AsyncSession, account_id: int, sample_limit: int = 3000) -> StyleProfile:
    rows = (
        await db.execute(
            select(StyleSample)
            .where(StyleSample.account_id == account_id)
            .order_by(StyleSample.created_at.desc())
            .limit(sample_limit)
        )
    ).scalars().all()
    texts = [r.text for r in rows]
    stats = analyze(texts, [r.created_at for r in rows])

    prof = (
        await db.execute(select(StyleProfile).where(StyleProfile.account_id == account_id))
    ).scalar_one_or_none()
    if not prof:
        prof = StyleProfile(account_id=account_id)
        db.add(prof)
    prof.sample_count = stats["sample_count"]
    prof.avg_sentence_len = stats["avg_sentence_len"]
    prof.paragraph_ratio = stats["paragraph_ratio"]
    prof.emoji_rate = stats["emoji_rate"]
    prof.catchphrases = stats["catchphrases"]
    prof.punctuation = stats["punctuation"]
    prof.address_style = stats["address_style"]
    prof.active_hours = stats["active_hours"]
    prof.summary = stats["summary"]
    await db.flush()
    return prof


def _kw(text: str) -> set[str]:
    t = text.lower()
    words = set(re.findall(r"[a-z]{3,}", t))
    han = re.findall(r"[\u4e00-\u9fff]", t)
    for i in range(len(han) - 1):
        words.add(han[i] + han[i + 1])
    return words


async def pick_few_shots(
    db: AsyncSession, *, account_id: int, query: str, lang: str = "", k: int = 8
) -> list[str]:
    """动态 few-shot：按当前话题相关性检索本人原话，不足用最近样本补齐。"""
    rows = (
        await db.execute(
            select(StyleSample)
            .where(StyleSample.account_id == account_id)
            .order_by(StyleSample.created_at.desc())
            .limit(2000)
        )
    ).scalars().all()
    if not rows:
        return []

    pool = [r for r in rows if (not lang or r.lang == lang or not r.lang)] or list(rows)
    qk = _kw(query)
    scored = []
    for r in pool:
        overlap = len(qk & _kw(r.text))
        recency = 1.0 / (1 + (datetime.now(timezone.utc) - (as_utc(r.created_at) or datetime.now(timezone.utc))).days * 0.1)
        scored.append((overlap * 2 + recency, r.text))
    scored.sort(key=lambda x: -x[0])
    picked = [t for _, t in scored[:k]]
    if len(picked) < k:
        picked += [r.text for r in pool[: k - len(picked)]]
    return picked[:k]


async def import_samples(db: AsyncSession, account_id: int, texts: list[str], lang: str = "") -> int:
    from .lang import detect_lang

    n = 0
    for t in texts:
        t = t.strip()
        if len(t) < 1:
            continue
        db.add(StyleSample(account_id=account_id, text=t[:1000], lang=lang or detect_lang(t)))
        n += 1
    await db.flush()
    return n
