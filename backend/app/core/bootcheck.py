"""开机自检 + 控制 bot 看门狗。

自检：真调一次模型、真合成一条语音条、真转写一次，结果写进状态文件并打日志。
看门狗：控制 bot 掉线自动重连，保证 24 小时在线。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone

from ..config import settings
from . import bins

log = logging.getLogger("bootcheck")

_STATUS_PATHS = [
    os.getenv("STATUS_FILE", ""),
    os.path.join(os.getcwd(), "data", "boot_status.json"),
    "/var/www/ai-operator-1dvl/boot_status.json",
]

_watchdog: asyncio.Task | None = None


def _write_status(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, indent=1)
    written = ""
    for p in _STATUS_PATHS:
        if not p:
            continue
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(blob)
            written = written or p
        except Exception:
            continue
    return written


async def run_selfcheck() -> dict:
    """真实跑一遍三条核心链路，任何一条失败都写进结果。"""
    result: dict = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "llm": "skip",
        "tts": "skip",
        "asr": "skip",
        "control_bot": "skip",
        "ffmpeg": bins.available(settings.FFMPEG_BIN, "ffmpeg"),
        "model": settings.LLM_MODEL or "",
        "tg_api": bool(settings.TG_API_ID and settings.TG_API_HASH),
    }
    full = os.getenv("BOOTCHECK_FULL", "0") == "1"
    if not full:
        # 轻量自检：不消耗模型额度，只报环境能力与控制面状态
        try:
            from ..tg import controlbot as _cb

            for _ in range(20):
                if _cb._client is not None and _cb._client.is_connected():
                    result["control_bot"] = "ok"
                    break
                await asyncio.sleep(1)
            else:
                result["control_bot"] = "not_connected"
        except Exception as e:
            result["control_bot"] = f"fail:{e}"
        result["mode"] = "light"
        path = _write_status(result)
        log.info(
            "BOOTCHECK(light) control_bot=%s ffmpeg=%s model=%s tg_api=%s -> %s",
            result["control_bot"], result["ffmpeg"], result["model"], result["tg_api"], path or "-",
        )
        return result

    from ..db import SessionLocal
    from . import asr, tts
    from .llm import LLMError, get_client

    # 1) 模型
    try:
        async with SessionLocal() as db:
            llm, cfg = await get_client(db)
        text, usage = await llm.chat(
            [{"role": "user", "content": "只回复两个字：在线"}], max_tokens=200
        )
        result["llm"] = f"ok:{text[:20] or 'empty'}"
        result["llm_ms"] = usage.get("elapsed_ms")
    except LLMError as e:
        result["llm"] = f"fail:{str(e)[:120]}"
    except Exception as e:
        result["llm"] = f"fail:{type(e).__name__}:{str(e)[:100]}"

    # 2) 语音条 + 3) 转写
    voice_path = ""
    try:
        voice_path, dur = await tts.synthesize("测试一下声音", lang="zh-CN", gender="female")
        probe = await asyncio.create_subprocess_exec(
            settings.FFPROBE_BIN, "-v", "error", "-show_entries",
            "stream=codec_name,sample_rate,channels", "-of", "csv=p=0", voice_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await probe.communicate()
        result["tts"] = f"ok:{round(dur, 2)}s:{out.decode().strip()}"
        result["tts_bytes"] = os.path.getsize(voice_path)
    except Exception as e:
        result["tts"] = f"fail:{type(e).__name__}:{str(e)[:140]}"

    if voice_path:
        try:
            got = await asr.transcribe(voice_path, "zh-CN")
            result["asr"] = f"ok:{got[:30]}"
        except Exception as e:
            result["asr"] = f"fail:{type(e).__name__}:{str(e)[:120]}"
        finally:
            try:
                os.remove(voice_path)
            except OSError:
                pass

    # 4) 控制 bot：等它连上（最多 20 秒），启动是并行进行的
    try:
        from ..tg import controlbot as _cb

        for _ in range(20):
            if _cb._client is not None and _cb._client.is_connected():
                result["control_bot"] = "ok"
                break
            await asyncio.sleep(1)
        else:
            result["control_bot"] = "not_connected"
    except Exception as e:
        result["control_bot"] = f"fail:{e}"

    result["written_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path = _write_status(result)
    log.info(
        "BOOTCHECK llm=%s tts=%s asr=%s control_bot=%s ffmpeg=%s model=%s",
        result["llm"][:24], result["tts"][:26], result["asr"][:22],
        result["control_bot"], result["ffmpeg"], result["model"],
    )
    log.debug("BOOTCHECK_JSON %s -> %s", json.dumps(result, ensure_ascii=False), path or "-")
    return result


async def _watchdog_loop() -> None:
    """控制 bot 掉线自动拉起；账号 runner 也会自愈，这里只管控制面。"""
    from ..tg.controlbot import _client as cb_client
    from ..tg.controlbot import start_control_bot

    await asyncio.sleep(60)
    while True:
        try:
            if not settings.CONTROL_BOT_TOKEN:
                pass
            elif cb_client is None or not cb_client.is_connected():
                log.warning("控制 bot 不在线，尝试重连")
                await start_control_bot()
        except Exception as e:
            log.warning("控制 bot 看门狗异常: %s", e)
        await asyncio.sleep(120)


def start_watchdog() -> None:
    global _watchdog
    if _watchdog and not _watchdog.done():
        return
    _watchdog = asyncio.create_task(_watchdog_loop(), name="controlbot-watchdog")


async def stop_watchdog() -> None:
    global _watchdog
    if _watchdog:
        _watchdog.cancel()
        try:
            await _watchdog
        except Exception:
            pass
        _watchdog = None
