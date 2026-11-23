"""端到端实测：模型 → 语音条 → 语音转文字，全部用真实服务。"""
import asyncio
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.core import asr, tts  # noqa: E402
from app.core.llm import get_client  # noqa: E402
from app.db import SessionLocal  # noqa: E402


async def main() -> None:
    async with SessionLocal() as db:
        llm, cfg = await get_client(db)
        text, usage = await llm.chat(
            [{"role": "system", "content": "你是客服助理"}, {"role": "user", "content": "用一句中文介绍一下你自己"}],
            max_tokens=80,
        )
        print("LLM_OK", usage.get("model"), usage.get("elapsed_ms"), "->", text[:60])

    cases = [
        ("zh-CN", "female", "今晚早点睡，别熬太晚，我等你消息。"),
        ("en", "male", "Hey, how was your day? Talk to me."),
        ("vi", "female", "Hôm nay bạn thế nào? Kể mình nghe đi."),
        ("km", "male", "សួស្តី! ថ្ងៃនេះអ្នកយ៉ាងម៉េចដែរ?"),
    ]
    for lang, gender, txt in cases:
        path, dur = await tts.synthesize(txt, lang=lang, gender=gender)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels",
             "-of", "csv=p=0", path],
            capture_output=True, text=True,
        ).stdout.strip()
        print(f"TTS_OK {lang} {gender} dur={round(dur,2)}s size={os.path.getsize(path)} probe={probe}")
        if lang in ("zh-CN", "km"):
            got = await asr.transcribe(path, lang)
            print(f"ASR_OK {lang} -> {got[:70]}")


asyncio.run(main())
