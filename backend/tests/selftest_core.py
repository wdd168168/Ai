"""核心链路自测：不依赖真实 Telegram 账号，验证引擎内部逻辑。

运行：.venv/bin/python tests/selftest_core.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./selftest.db")
os.environ.setdefault("QUEUE_BACKEND", "inline")
os.environ.setdefault("MEDIA_DIR", "./testmedia")
os.environ.setdefault("SECRET_KEY", "selftest")

from app.core import lang as L  # noqa: E402
from app.core import style as S  # noqa: E402
from app.core.typing import in_active_hours, plan_send, typing_seconds  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name} {extra}")


def test_lang() -> None:
    check("高棉语检测", L.detect_lang("សួស្តី ខ្ញុំសុខសប្បាយ") == "km")
    check("越南语检测", L.detect_lang("Hôm nay bạn có rảnh không?") == "vi")
    check("英语检测", L.detect_lang("what are you doing tonight") == "en")
    check("简体检测", L.detect_lang("你在干嘛呢，今天上班累不累") == "zh-CN")
    check("繁体检测", L.detect_lang("你在幹嘛呢，今天上班累不累") == "zh-TW")
    check("台语检测", L.detect_lang("阮今仔日欲去遮，汝佮我作伙去") == "nan-TW",
          f"-> {L.detect_lang('阮今仔日欲去遮，汝佮我作伙去')}")

    # 台湾用语本地化
    tw = L.apply_language("这个软件的视频信息默认支持打印", "zh-TW")
    check("台湾用语替换", ("軟體" in tw and "影片" in tw and "預設" in tw and "支援" in tw), f"-> {tw}")
    check("繁体化无简体残留", L.check_mixed_script(tw) == [], f"-> {tw} {L.check_mixed_script(tw)}")

    cn = L.apply_language("這個軟體的影片資訊預設支援列印", "zh-CN")
    check("繁转简+大陆用词", "软件" in cn and "视频" in cn and "预设" in cn, f"-> {cn}")

    mixed = "这个软件的功能們都很好"
    check("混用检测", len(L.check_mixed_script(mixed)) > 0, f"-> {L.check_mixed_script(mixed)}")

    check("台语与台湾国语是不同选项", L.LANGS["nan-TW"] != L.LANGS["zh-TW"])


def test_typing() -> None:
    text = "刚下班，累死了。你今天吃饭了没？要不要一起叫个外卖"
    plan = plan_send(text, persona_paragraph="拆条", is_stranger=False, voice_ratio=0)
    check("拆条 1-3 条", 1 <= len(plan.parts) <= 3, f"-> {len(plan.parts)} 条")
    check("不秒回（已读延迟 ≥3s）", plan.read_delay >= 3, f"-> {plan.read_delay}s")
    check("已读延迟 ≤90s", plan.read_delay <= 90, f"-> {plan.read_delay}s")
    check("打字时长 > 0", all(t > 0 for t in plan.typing), f"-> {plan.typing}")
    check("条间间隔 1-3s", all(1.0 <= g <= 3.0 for g in plan.gaps), f"-> {plan.gaps}")

    t_short = typing_seconds("嗯")
    t_long = typing_seconds("今天在外面跑了一整天，刚回到住的地方，累得不想动，你呢，吃饭了没")
    check("打字时长与字数正相关", t_long > t_short, f"-> {t_short}s vs {t_long}s")

    stranger = plan_send("在吗", is_stranger=True, rng=__import__("random").Random(1))
    check("陌生首条 10-60s", 10 <= stranger.read_delay <= 60, f"-> {stranger.read_delay}s")

    check("作息内", in_active_hours("Asia/Phnom_Penh", {"start": "09:00", "end": "23:00"},
                                  datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc)))
    check("凌晨不在线", not in_active_hours("Asia/Phnom_Penh", {"start": "09:00", "end": "23:00"},
                                         datetime(2026, 11, 20, 19, 0, tzinfo=timezone.utc)))


def test_style() -> None:
    texts = [
        "刚下班\n累死了",
        "你先吃饭啊，别等我",
        "哈哈哈哈哈笑死",
        "真的假的，你认真的吗？",
        "我也不知道诶，看心情吧",
        "刚下班\n累死了",
    ]
    prof = S.analyze(texts)
    check("风格样本数正确", prof["sample_count"] == 6, f"-> {prof['sample_count']}")
    check("分段比例被统计出", prof["paragraph_ratio"] > 0, f"-> {prof['paragraph_ratio']}")
    check("emoji/语气统计可算", isinstance(prof["emoji_rate"], float))
    check("生成了风格摘要", bool(prof["summary"]), f"-> {prof['summary']}")

    texts2 = ["真的假的啊"] * 3 + ["你认真的吗"] * 3 + ["笑死我了啦"] * 3
    caps = S.extract_catchphrases(texts2)
    check("能抽出重复口头禅", len(caps) > 0, f"-> {caps}")


def _start_mock() -> None:
    """在进程内起 mock 模型端点，确保自测不依赖外部进程。"""
    import threading
    from http.server import ThreadingHTTPServer

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mock_llm import H

    srv = ThreadingHTTPServer(("127.0.0.1", 8791), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


async def test_llm_chain() -> None:
    """完整生成链路（对接本地 mock 模型）。"""
    _start_mock()
    from app.db import init_db, SessionLocal
    from app.models import Account, Contact, Message, Persona
    from app.tg.handlers import generate_reply
    from app.core.llm import LLMConfig, LLMClient
    from sqlalchemy import select

    await init_db()
    async with SessionLocal() as db:
        from app.seed import seed_personas

        await seed_personas(db)
        await db.commit()
        p = (await db.execute(select(Persona))).scalars().first()
        if not p:
            p = Persona(name="测试人设", traits=["温柔"], catchphrases=["你先吃饭"], gender="female")
            db.add(p)
            await db.flush()
        acc = Account(phone="+855000", persona_id=p.id, status="online")
        db.add(acc)
        await db.flush()
        c = Contact(account_id=acc.id, tg_id=999001, first_name="阿明", lang="zh-CN")
        db.add(c)
        await db.flush()
        db.add(Message(account_id=acc.id, contact_id=c.id, direction="in", text="在干嘛", source="contact"))
        from app.models import Setting

        db.add(Setting(key="llm_config", value={
            "base_url": "http://127.0.0.1:8791/v1", "api_key": "mock", "model": "mock-model",
            "temperature": 0.9, "max_tokens": 200,
        }))
        await db.commit()
        aid, cid = acc.id, c.id

    try:
        text, lang, meta = await generate_reply(aid, cid, "在干嘛")
        check("生成链路跑通", bool(text), f"-> {text!r}")
        check("返回语言正确", lang == "zh-CN", f"-> {lang}")
        check("带上人设元信息", meta.get("persona_id") is not None)
        check("记录了使用的记忆/风格槽位", "memory_used" in meta and "style_refs" in meta)
        check("简繁一致", L.check_mixed_script(text) == [] if lang == "zh-TW" else True)
    except Exception as e:
        check("生成链路跑通", False, f"异常: {e}")

    # 三个人设 → 系统提示词必须明显不同
    from app.core.persona import build_system_prompt
    from app.models import StyleProfile

    async with SessionLocal() as db:
        ps = (await db.execute(select(Persona).limit(3))).scalars().all()
        acc = await db.get(Account, aid)
        c = await db.get(Contact, cid)
        prompts = [
            build_system_prompt(persona=p, account=acc, contact=c, lang="zh-CN", lang_mode="follow",
                                facts=[], style=None, few_shots=[], stranger=False)
            for p in ps
        ]
        check("三个人设的提示词不同", len(set(prompts)) == 3)
        check("提示词含禁忌与语气档", "禁忌话题" in prompts[0] and "语气浓度" in prompts[0])
        check("提示词禁止暴露 AI 身份", "绝不承认自己是 AI" in prompts[0])

    # 记忆抽取（mock 返回 JSON）
    from app.core import memory as M

    async with SessionLocal() as db:
        llm = LLMClient(LLMConfig(base_url="http://127.0.0.1:8791/v1", api_key="mock", model="mock-model"))
        contact = await db.get(Contact, cid)
        saved = await M.extract_facts(llm, db=db, account_id=aid, contact_id=cid,
                                     history=[("in", "下周三我要去曼谷出差"), ("out", "这么突然")], known=[])
        await db.commit()
        check("记忆抽取写库", len(saved) >= 1, f"-> {[s.content for s in saved]}")
        facts = await M.retrieve_facts(db, account_id=aid, contact_id=cid, query="曼谷 出差")
        check("记忆检索命中", any("曼谷" in f.content for f in facts), f"-> {[f.content for f in facts]}")
        # 不串台
        other = Contact(account_id=aid, tg_id=999002, first_name="另一个")
        db.add(other)
        await db.flush()
        facts2 = await M.retrieve_facts(db, account_id=aid, contact_id=other.id, query="曼谷 出差")
        check("记忆不串台", len(facts2) == 0, f"-> {len(facts2)}")

    # 画像更新
    from app.core import profile as P

    async with SessionLocal() as db:
        llm = LLMClient(LLMConfig(base_url="http://127.0.0.1:8791/v1", api_key="mock", model="mock-model"))
        contact = await db.get(Contact, cid)
        await P.update_profile(llm, db, contact=contact,
                               history=[("in", "我最近在健身"), ("out", "厉害"), ("in", "每天去"), ("out", "牛")])
        await db.commit()
        check("画像写入兴趣", len(contact.interests) > 0, f"-> {contact.interests}")
        check("画像写入情绪基线", contact.emotion_baseline in ("positive", "neutral", "low", "anxious"))


async def main() -> None:
    test_lang()
    test_typing()
    test_style()
    await test_llm_chain()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
