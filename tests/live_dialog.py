"""真实模型对话实测：多语言、多人设、记忆上下文。用独立测试库，不碰正式数据。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Account, Contact, Persona  # noqa: E402
from app.seed import seed_personas  # noqa: E402
from app.tg.handlers import generate_reply  # noqa: E402


async def setup() -> tuple[int, int, list[int]]:
    await init_db()
    async with SessionLocal() as db:
        await seed_personas(db)
        await db.commit()
        personas = (await db.execute(select(Persona).order_by(Persona.id))).scalars().all()
        acc = (
            await db.execute(select(Account).where(Account.phone == "+10000000000"))
        ).scalars().first()
        if not acc:
            acc = Account(phone="+10000000000", label="测试号", status="online",
                          api_id="1", api_hash="x", persona_id=personas[0].id)
            db.add(acc)
            await db.commit()
            await db.refresh(acc)
        c = (await db.execute(select(Contact).where(Contact.tg_id == 777))).scalars().first()
        if not c:
            c = Contact(account_id=acc.id, tg_id=777, first_name="阿明", username="aming")
            db.add(c)
            await db.commit()
            await db.refresh(c)
        return acc.id, c.id, [p.id for p in personas]


async def main() -> None:
    aid, cid, pids = await setup()
    cases = [
        ("你好呀，今天忙不忙？", "zh"),
        ("Hey, how's your day going?", "en"),
        ("Hôm nay bạn có rảnh không?", "vi"),
    ]
    for text, tag in cases:
        reply, lang, meta = await generate_reply(aid, cid, text)
        print(f"[{tag}] 语言={lang} 人设={meta['persona_name']} 语音比={meta['voice_ratio']}%")
        print("   对方:", text)
        print("   回复:", reply.replace("\n", " / ")[:160])

    # 同一条消息换三个人设，看风格是否明显不同
    print("\n== 三人设对比（同一条消息）==")
    async with SessionLocal() as db:
        acc = await db.get(Account, aid)
        for pid in pids[:3]:
            p = await db.get(Persona, pid)
            acc.persona_id = pid
            await db.commit()
            reply, lang, meta = await generate_reply(aid, cid, "你在做什么呀？")
            print(f"- {p.name} → {reply.replace(chr(10), ' / ')[:100]}")


asyncio.run(main())
