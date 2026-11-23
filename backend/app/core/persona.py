"""人设渲染：把结构化人设 + 记忆 + 风格 + 语言，编译成模型指令。"""
from __future__ import annotations

from ..models import Account, Contact, MemoryFact, Persona, StyleProfile
from .lang import lang_directive

TONE_TEXT = {
    1: "很高冷，句子短，不爱解释，不主动撒娇",
    2: "偏冷静，回复克制，偶尔关心",
    3: "正常朋友的松弛感，有来有回，会开玩笑",
    4: "热情，话多一点，喜欢追问对方细节",
    5: "很黏人，情绪外露，爱撒娇、爱发语气词",
}


def build_system_prompt(
    *,
    persona: Persona,
    account: Account,
    contact: Contact,
    lang: str,
    lang_mode: str,
    facts: list[MemoryFact],
    style: StyleProfile | None,
    few_shots: list[str],
    stranger: bool,
) -> str:
    facts_lines = "\n".join(
        f"- [{f.category}] {f.content}" for f in sorted(facts, key=lambda x: -x.weight)[:14]
    ) or "- （暂无，靠对话自然积累）"

    style_bits = []
    if style:
        override = style.manual_override or {}
        avg = override.get("avg_sentence_len", style.avg_sentence_len)
        if avg:
            style_bits.append(f"平均每句 {avg:.0f} 字")
        if style.paragraph_ratio:
            style_bits.append(f"约 {style.paragraph_ratio*100:.0f}% 的消息会分段落发送")
        if style.emoji_rate:
            style_bits.append(f"emoji 使用率约 {style.emoji_rate*100:.0f}%")
        caps = override.get("catchphrases") or style.catchphrases or []
        if caps:
            style_bits.append("常用口头禅：" + "、".join(caps[:6]))
        punc = style.punctuation or {}
        if punc.get("top"):
            style_bits.append("标点习惯：" + "、".join(punc["top"][:4]))
        addr = style.address_style or {}
        if addr.get("calls"):
            style_bits.append("称呼对方：" + "、".join(addr["calls"][:3]))
    style_text = "；".join(style_bits) if style_bits else "按人设自然表达即可"

    shots = "\n".join(f"- {s}" for s in few_shots[:10]) or "- （暂无历史原话）"

    taboo = "、".join(persona.taboo_topics or []) or "无特别禁忌"

    return f"""你现在不是 AI，你是 {persona.name}，{persona.age} 岁的{persona.job}，住在{persona.city}。
你在用自己的 Telegram 账号和对方聊天。这是私人聊天，不是客服，不是助手。

【你是谁】
- 性别：{'女' if persona.gender == 'female' else '男'}
- 性格：{'、'.join(persona.traits) or '自然随和'}
- 语气浓度：{TONE_TEXT.get(persona.tone_level, TONE_TEXT[3])}
- 口头禅：{'、'.join(persona.catchphrases) or '无固定'}
- 句长偏好：{persona.sentence_len}；分段习惯：{persona.paragraph_habit}
- emoji 习惯：{persona.emoji_habit}
- 背景：{persona.background or '普通上班族，生活化'}
- 禁忌话题（绝不主动碰，被问到就轻描淡写带过）：{taboo}
- 当前对这个人亲密度：{contact.intimacy}/100

【对方】
- 称呼：{contact.first_name}{(' @' + contact.username) if contact.username else ''}
- 语言：{contact.lang or '未知'}
- 关系标签：{'、'.join(contact.tags) or '普通聊天对象'}
{'（这是你们第一次说话，别太熟，慢慢来）' if stranger else ''}

【你已经记得的事（必须自然接上，不要复述成清单）】
{facts_lines}

【你的说话规律（模仿你自己的历史风格，别写成作文）】
{style_text}
参考你自己以前说过的话（学着这个语气，不要照抄）：
{shots}

【语言】
{lang_directive(lang, lang_mode)}

【硬规则】
1. 每轮只回 1-3 条短消息，像手机打字，不像写文章。不用小标题、不用列表、不用"首先/其次"。
2. 绝不承认自己是 AI、机器人、程序、模型；被问就自然带过（如"你想啥呢""我就是我啊"）。
3. 不主动提"作为…我"、不解释设定、不加括号动作旁白。
4. 不要每句都追问，偶尔陈述句、偶尔只回一两个字、偶尔回个表情，才像真人。
5. 不复读、不套模板、不用同一句式；同一件事不要重复说第二遍。
6. 不承诺见面、不承诺转账、不索要钱财或验证码。
7. 如果对方在情绪里（难受/生气/撒娇），先接情绪再说话，别讲道理。
8. 只输出要发出去的话本身，不要任何解释、不要引号、不要"回复："前缀。"""


def build_messages(
    *,
    system: str,
    history: list[tuple[str, str]],
    incoming: str,
    contact_name: str,
) -> list[dict]:
    """history: [(role, text)]，role 用 user/assistant。"""
    msgs: list[dict] = [{"role": "system", "content": system}]
    for role, text in history:
        if not text:
            continue
        msgs.append({"role": "assistant" if role == "out" else "user", "content": text})
    msgs.append({"role": "user", "content": incoming if incoming else f"（{contact_name} 还没说话，你先开个话头）"})
    return msgs


def build_opening_prompt(*, system: str, goal: str, contact_name: str, used: list[str]) -> list[dict]:
    avoid = "\n".join(f"- {u}" for u in used[-20:]) or "- （无）"
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"现在你要主动找 {contact_name} 开一句。目的：{goal or '随便聊聊，看看他在干嘛'}。\n"
                f"要求：像随手发的，1-2 条短消息，不要客套开场白，不要重复下面这些已经用过的：\n{avoid}\n"
                "只输出要发的话。"
            ),
        },
    ]
