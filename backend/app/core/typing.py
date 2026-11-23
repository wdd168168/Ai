"""拟人化节奏引擎（硬指标）。所有发送都经过这里，不允许秒回。

- 打字时长按字数模拟：约每 3-5 字/秒
- 一条回复拆 1-3 条发送，条间 1-3 秒
- 已读随机延迟 3-90 秒
- 陌生会话首条延迟 10-60 秒
- 按人设作息模拟在线，不在凌晨异常活跃
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CHARS_PER_SEC_MIN = 3.0
CHARS_PER_SEC_MAX = 5.0


def _text_len(text: str) -> int:
    """按"有效字数"计：汉字/高棉文/泰文 1 字，拉丁按 4 字符≈1 字。"""
    han = len(re.findall(r"[\u4e00-\u9fff\u1780-\u17ff\u0e00-\u0e7f]", text))
    latin = len(re.findall(r"[A-Za-z0-9]", text))
    other = len(text) - han - latin
    return int(han + latin / 4 + other * 0.3)


def typing_seconds(text: str, rng: random.Random | None = None) -> float:
    r = rng or random
    n = max(1, _text_len(text))
    speed = r.uniform(CHARS_PER_SEC_MIN, CHARS_PER_SEC_MAX)
    base = n / speed
    # 按键间隔抖动 + 起步思考
    base += r.uniform(0.6, 1.8)
    return round(min(max(base, 1.2), 45.0), 2)


def read_delay(is_stranger: bool = False, rng: random.Random | None = None) -> float:
    r = rng or random
    if is_stranger:
        return round(r.uniform(10, 60), 1)
    # 多数在 3-45 秒，少数拖到 90
    v = r.triangular(3, 90, 12)
    return round(v, 1)


def split_messages(
    text: str, max_parts: int = 3, prefer: str = "拆条", rng: random.Random | None = None
) -> list[str]:
    """把回复拆成 1-3 条自然消息。拆点优先：空行 > 句末标点 > 逗号。"""
    r = rng or random
    text = text.strip()
    if not text:
        return []
    if prefer == "整条" or max_parts <= 1:
        return [text]

    # 已有换行的，按行合并
    blocks = [b.strip() for b in re.split(r"\n{1,}", text) if b.strip()]
    if len(blocks) >= 2:
        parts = blocks[:max_parts]
        if len(blocks) > max_parts:
            parts[-1] = " ".join([parts[-1], *blocks[max_parts:]])
        return parts

    sentences = re.split(r"(?<=[。！？!?…~])\s*", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) <= 1:
        if _text_len(text) > 40 and r.random() < 0.6:
            mid = len(text) // 2
            cut = text.rfind("，", 0, mid + 10)
            if cut < 10:
                cut = mid
            return [text[: cut + 1].strip(), text[cut + 1 :].strip()]
        return [text]

    target = min(max_parts, len(sentences))
    if target == 1:
        return [text]
    per = math.ceil(len(sentences) / target)
    parts = ["".join(sentences[i : i + per]) for i in range(0, len(sentences), per)]
    return [p.strip() for p in parts if p.strip()][:max_parts]


def parse_hhmm(s: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        h, m = s.strip().split(":")
        return int(h), int(m)
    except Exception:
        return default


def in_active_hours(timezone: str, active_hours: dict, now: datetime | None = None) -> bool:
    try:
        tz = ZoneInfo(timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = (now or datetime.now(tz)).astimezone(tz)
    start = parse_hhmm(str(active_hours.get("start", "09:00")), (9, 0))
    end = parse_hhmm(str(active_hours.get("end", "23:30")), (23, 30))
    cur = local.hour * 60 + local.minute
    s = start[0] * 60 + start[1]
    e = end[0] * 60 + end[1]
    if s <= e:
        return s <= cur <= e
    return cur >= s or cur <= e  # 跨午夜


def next_active_time(timezone: str, active_hours: dict, now: datetime | None = None) -> datetime:
    try:
        tz = ZoneInfo(timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = (now or datetime.now(tz)).astimezone(tz)
    s = parse_hhmm(str(active_hours.get("start", "09:00")), (9, 0))
    target = local.replace(hour=s[0], minute=s[1], second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target


def online_jitter(timezone: str, active_hours: dict, rng: random.Random | None = None) -> bool:
    """作息内的在线抖动：即使在活跃时段，也有 8% 概率"不在手机旁"。"""
    r = rng or random
    if not in_active_hours(timezone, active_hours):
        return False
    return r.random() > 0.08


def should_use_voice(voice_ratio: int, scene: str = "", rng: random.Random | None = None) -> bool:
    r = rng or random
    ratio = max(0, min(100, int(voice_ratio)))
    if scene in ("goodnight", "comfort", "flirt_voice"):
        ratio = min(100, ratio + 35)
    return r.randint(1, 100) <= ratio


@dataclass
class SendPlan:
    """一次回复的完整发送计划：已读延迟 → 逐条打字 → 条间间隔。"""

    parts: list[str] = field(default_factory=list)
    read_delay: float = 0.0
    typing: list[float] = field(default_factory=list)
    gaps: list[float] = field(default_factory=list)
    use_voice: bool = False
    total_seconds: float = 0.0


def plan_send(
    text: str,
    *,
    persona_paragraph: str = "拆条",
    is_stranger: bool = False,
    voice_ratio: int = 0,
    scene: str = "",
    rng: random.Random | None = None,
) -> SendPlan:
    r = rng or random.Random()
    parts = split_messages(text, 3, persona_paragraph, rng=r)
    if not parts:
        return SendPlan()
    typing = [typing_seconds(p, rng=r) for p in parts]
    gaps = [round(r.uniform(1.0, 3.0), 2) for _ in range(max(0, len(parts) - 1))]
    use_voice = should_use_voice(voice_ratio, scene, rng=r)
    rd = read_delay(is_stranger, rng=r)
    total = rd + sum(typing) + sum(gaps)
    return SendPlan(
        parts=parts, read_delay=rd, typing=typing, gaps=gaps, use_voice=use_voice, total_seconds=round(total, 1)
    )
