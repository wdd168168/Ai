"""多语种 TTS 路由 + 语音条格式（ogg/opus 单声道 48kHz）。

音色目录里标注了每个音色需要哪个 provider：
- edge：微软 Edge 朗读通道，无需 key，开箱可用
- azure / google / openai：需要对应 key
- clone：用上传的 30s-3min 样本克隆出来的音色
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass

import httpx

from ..config import settings
from . import bins

# 语种 → 性别 → 音色列表
VOICE_CATALOG: dict[str, dict[str, list[dict]]] = {
    "zh-CN": {
        "female": [
            {"id": "zh-CN-XiaoxiaoNeural", "provider": "edge", "name": "晓晓·温柔"},
            {"id": "zh-CN-XiaoyiNeural", "provider": "edge", "name": "晓伊·活泼"},
            {"id": "zh-CN-XiaohanNeural", "provider": "edge", "name": "晓涵·知性"},
            {"id": "zh-CN-XiaomengNeural", "provider": "edge", "name": "晓梦·甜"},
            {"id": "zh-CN-XiaoxuanNeural", "provider": "azure", "name": "晓萱·故事感"},
        ],
        "male": [
            {"id": "zh-CN-YunxiNeural", "provider": "edge", "name": "云希·少年感"},
            {"id": "zh-CN-YunjianNeural", "provider": "edge", "name": "云健·低沉"},
            {"id": "zh-CN-YunyangNeural", "provider": "edge", "name": "云扬·播音"},
            {"id": "zh-CN-YunxiaNeural", "provider": "azure", "name": "云夏·少年"},
        ],
    },
    "zh-TW": {
        "female": [
            {"id": "zh-TW-HsiaoChenNeural", "provider": "edge", "name": "曉臻·台灣女聲"},
            {"id": "zh-TW-HsiaoYuNeural", "provider": "edge", "name": "曉雨·台灣女聲"},
            {"id": "zh-TW-HsiaoChenNeural", "provider": "azure", "name": "曉臻·情緒版"},
            {"id": "zh-TW-HsiaoYuNeural", "provider": "azure", "name": "曉雨·情緒版"},
        ],
        "male": [
            {"id": "zh-TW-YunJheNeural", "provider": "edge", "name": "雲哲·台灣男聲"},
            {"id": "zh-TW-YunJheNeural", "provider": "azure", "name": "雲哲·情緒版"},
            {"id": "clone", "provider": "clone", "name": "克隆音色（30s-3min 样本）"},
        ],
    },
    # 台语（闽南语）：无原生商用音色，走克隆音色或 zh-TW 音色读台语用字
    "nan-TW": {
        "female": [
            {"id": "clone", "provider": "clone", "name": "克隆音色（台语样本）"},
            {"id": "zh-TW-HsiaoChenNeural", "provider": "edge", "name": "曉臻·讀台語用字"},
        ],
        "male": [
            {"id": "clone", "provider": "clone", "name": "克隆音色（台语样本）"},
            {"id": "zh-TW-YunJheNeural", "provider": "edge", "name": "雲哲·讀台語用字"},
        ],
    },
    "en": {
        "female": [
            {"id": "en-US-AriaNeural", "provider": "edge", "name": "Aria"},
            {"id": "en-US-JennyNeural", "provider": "edge", "name": "Jenny"},
            {"id": "en-GB-SoniaNeural", "provider": "edge", "name": "Sonia (UK)"},
            {"id": "en-AU-NatashaNeural", "provider": "edge", "name": "Natasha (AU)"},
        ],
        "male": [
            {"id": "en-US-GuyNeural", "provider": "edge", "name": "Guy"},
            {"id": "en-US-DavisNeural", "provider": "edge", "name": "Davis"},
            {"id": "en-GB-RyanNeural", "provider": "edge", "name": "Ryan (UK)"},
            {"id": "en-AU-WilliamNeural", "provider": "edge", "name": "William (AU)"},
        ],
    },
    "vi": {
        "female": [
            {"id": "vi-VN-HoaiMyNeural", "provider": "edge", "name": "Hoài My"},
            {"id": "clone", "provider": "clone", "name": "克隆音色（越南语样本）"},
            {"id": "vi-VN-HoaiMyNeural", "provider": "azure", "name": "Hoài My · Azure"},
        ],
        "male": [
            {"id": "vi-VN-NamMinhNeural", "provider": "edge", "name": "Nam Minh"},
            {"id": "clone", "provider": "clone", "name": "克隆音色（越南语样本）"},
            {"id": "vi-VN-NamMinhNeural", "provider": "azure", "name": "Nam Minh · Azure"},
        ],
    },
    "km": {
        "female": [
            {"id": "km-KH-SreymomNeural", "provider": "edge", "name": "ស្រីមុំ"},
            {"id": "clone", "provider": "clone", "name": "克隆音色（高棉语样本）"},
        ],
        "male": [
            {"id": "km-KH-PisethNeural", "provider": "edge", "name": "ពិសិដ្ឋ"},
            {"id": "clone", "provider": "clone", "name": "克隆音色（高棉语样本）"},
        ],
    },
}

# 语种 → edge 音色的 language 参数（台语回退到 zh-TW 发音）
EDGE_LOCALE = {
    "zh-CN": "zh-CN",
    "zh-TW": "zh-TW",
    "nan-TW": "zh-TW",
    "en": "en-US",
    "vi": "vi-VN",
    "km": "km-KH",
}

DEFAULT_VOICE = {
    "zh-CN": {"female": "zh-CN-XiaoxiaoNeural", "male": "zh-CN-YunxiNeural"},
    "zh-TW": {"female": "zh-TW-HsiaoChenNeural", "male": "zh-TW-YunJheNeural"},
    "nan-TW": {"female": "zh-TW-HsiaoChenNeural", "male": "zh-TW-YunJheNeural"},
    "en": {"female": "en-US-AriaNeural", "male": "en-US-GuyNeural"},
    "vi": {"female": "vi-VN-HoaiMyNeural", "male": "vi-VN-NamMinhNeural"},
    "km": {"female": "km-KH-SreymomNeural", "male": "km-KH-PisethNeural"},
}


def pick_voice(lang: str, gender: str, preferred: str = "") -> str:
    if preferred and preferred not in ("clone",):
        return preferred
    return DEFAULT_VOICE.get(lang, DEFAULT_VOICE["zh-CN"]).get(
        gender if gender in ("female", "male") else "female"
    )


def voices_for(lang: str, gender: str) -> list[dict]:
    cat = VOICE_CATALOG.get(lang) or VOICE_CATALOG["zh-CN"]
    return cat.get(gender, [])


async def to_ogg_opus(src: str, dst: str) -> float:
    """转成 Telegram 语音条格式：ogg / opus / 单声道 / 48kHz。返回时长秒。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    cmd = [
        bins.resolve(settings.FFMPEG_BIN, "ffmpeg"), "-y", "-i", src,
        "-c:a", "libopus", "-b:a", "48k", "-ar", "48000", "-ac", "1",
        "-application", "voip", dst,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 转码失败: {err.decode()[-300:]}")
    return await probe_duration(dst)


async def probe_duration(path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        bins.resolve(settings.FFPROBE_BIN, "ffprobe"), "-v", "quiet", "-show_entries", "format=duration",
        "-of", "default=nk=1:nw=1", path,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        return round(float(out.decode().strip()), 2)
    except Exception:
        return 0.0


# ---------- providers ----------
async def _edge_tts(text: str, voice: str, rate: str, pitch: str, out_path: str, lang: str) -> None:
    import edge_tts

    kwargs = {"voice": voice, "rate": rate, "pitch": pitch}
    # edge 的 voice 已含语种；台语回退时保持 zh-TW 音色但文本是台语用字
    communicate = edge_tts.Communicate(text, **kwargs)
    await communicate.save(out_path)


async def _concat_mp3(files: list[str], out_path: str) -> None:
    lst = tempfile.mktemp(suffix=".txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for f in files:
            fh.write(f"file '{f}'\n")
    proc = await asyncio.create_subprocess_exec(
        bins.resolve(settings.FFMPEG_BIN, "ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out_path,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"音频拼接失败: {err.decode()[-200:]}")


def _chunks(text: str, size: int = 18) -> list[str]:
    """按标点/空格切句；某些语种（高棉文）长句会让服务端返回空音频，短句更稳。"""
    parts = [x for x in re.split(r"(?<=[。！？!?；;，,、.])|\s{1,}", text) if x and x.strip()]
    if len(parts) <= 1 or max(len(x) for x in parts) > 80:
        parts = [text[i : i + 60] for i in range(0, len(text), 60)] if len(text) > 60 else parts
    merged: list[str] = []
    buf = ""
    for p in parts:
        if len(buf) + len(p) <= 60:
            buf += p
        else:
            if buf:
                merged.append(buf)
            buf = p
    if buf:
        merged.append(buf)
    return merged or [text[:60]]


async def _edge_tts_robust(text: str, voice: str, rate: str, pitch: str, out_path: str) -> None:
    """先整句；服务端返回空音频时逐句重试并拼接（高棉语等小语种常见）。"""
    try:
        await _edge_tts(text, voice, rate, pitch, out_path, "")
        if os.path.getsize(out_path) > 1200:
            return
    except Exception:
        pass

    pieces = _chunks(text)
    if len(pieces) <= 1:
        raise RuntimeError("edge 无音频返回")
    files: list[str] = []
    for piece in pieces:
        f = tempfile.mktemp(suffix=".mp3")
        for attempt in range(2):
            try:
                await _edge_tts(piece, voice, rate, pitch, f, "")
                if os.path.getsize(f) > 500:
                    files.append(f)
                    break
            except Exception:
                await asyncio.sleep(0.4)
    if not files:
        raise RuntimeError("edge 无音频返回")
    if len(files) == 1:
        os.replace(files[0], out_path)
        return
    await _concat_mp3(files, out_path)
    for f in files:
        try:
            os.remove(f)
        except OSError:
            pass


async def _gtts_tts(text: str, lang: str, out_path: str) -> None:
    """备用通道：Google 朗读接口，无需 key，支持 km/vi/zh/en（台语回退 zh-TW）。"""
    code = {"zh-CN": "zh-CN", "zh-TW": "zh-TW", "nan-TW": "zh-TW", "en": "en", "vi": "vi", "km": "km"}.get(
        lang, "zh-CN"
    )
    chunks = [text[i : i + 160] for i in range(0, len(text), 160)]
    files: list[str] = []
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as c:
        for ch in chunks:
            r = await c.get(
                "https://translate.google.com/translate_tts",
                params={"ie": "UTF-8", "q": ch, "tl": code, "client": "tw-ob"},
            )
            if r.status_code != 200 or len(r.content) < 500:
                raise RuntimeError(f"备用语音通道失败 HTTP {r.status_code}")
            f = tempfile.mktemp(suffix=".mp3")
            with open(f, "wb") as fh:
                fh.write(r.content)
            files.append(f)
    if len(files) == 1:
        os.replace(files[0], out_path)
        return
    await _concat_mp3(files, out_path)


async def _openai_tts(text: str, voice: str, out_path: str) -> None:
    if not settings.TTS_OPENAI_API_KEY:
        raise RuntimeError("未配置 TTS_OPENAI_API_KEY")
    payload = {
        "model": settings.TTS_OPENAI_MODEL or "tts-1",
        "voice": voice if voice in ("alloy", "echo", "fable", "onyx", "nova", "shimmer") else "nova",
        "input": text,
        "response_format": "mp3",
    }
    async with httpx.AsyncClient(timeout=settings.TTS_TIMEOUT) as c:
        r = await c.post(
            f"{settings.TTS_OPENAI_BASE_URL.rstrip('/')}/audio/speech",
            json=payload,
            headers={"Authorization": f"Bearer {settings.TTS_OPENAI_API_KEY}"},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI TTS {r.status_code}: {r.text[:200]}")
        with open(out_path, "wb") as f:
            f.write(r.content)


async def _azure_tts(text: str, voice: str, out_path: str, rate: float, pitch: float) -> None:
    if not (settings.TTS_AZURE_KEY and settings.TTS_AZURE_REGION):
        raise RuntimeError("未配置 Azure 语音密钥")
    ssml = f"""<speak version='1.0' xml:lang='{voice[:5]}'>
<voice name='{voice}'><prosody rate='{int((rate-1)*100):+d}%' pitch='{int((pitch-1)*50):+d}%'>{text}</prosody></voice></speak>"""
    url = f"https://{settings.TTS_AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": settings.TTS_AZURE_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
    }
    async with httpx.AsyncClient(timeout=settings.TTS_TIMEOUT) as c:
        r = await c.post(url, content=ssml.encode(), headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"Azure TTS {r.status_code}: {r.text[:200]}")
        with open(out_path, "wb") as f:
            f.write(r.content)


async def _clone_tts(text: str, voice_id: str, out_path: str) -> None:
    """ElevenLabs 兼容的克隆音色接口（base_url + key 可配）。"""
    base = os.getenv("TTS_CLONE_BASE_URL", "").rstrip("/")
    key = os.getenv("TTS_CLONE_API_KEY", "")
    if not base or not key or voice_id in ("", "clone"):
        raise RuntimeError("克隆音色未配置：需要 TTS_CLONE_BASE_URL / TTS_CLONE_API_KEY 和 voice_id")
    async with httpx.AsyncClient(timeout=settings.TTS_TIMEOUT) as c:
        r = await c.post(
            f"{base}/v1/text-to-speech/{voice_id}",
            json={"text": text, "model_id": os.getenv("TTS_CLONE_MODEL", "eleven_multilingual_v2")},
            headers={"xi-api-key": key, "Accept": "audio/mpeg"},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"克隆 TTS {r.status_code}: {r.text[:200]}")
        with open(out_path, "wb") as f:
            f.write(r.content)


def _provider_of(voice: str) -> str:
    for lang, g in VOICE_CATALOG.items():
        for gender, items in g.items():
            for it in items:
                if it["id"] == voice:
                    return it["provider"]
    if voice.startswith(("zh-", "en-", "vi-", "km-")):
        return "edge"
    return "openai"


async def synthesize(
    text: str,
    *,
    lang: str,
    gender: str,
    voice: str = "",
    rate: float = 1.0,
    pitch: float = 1.0,
    out_dir: str | None = None,
) -> tuple[str, float]:
    """生成语音条文件。返回 (path, duration)。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("空文本")
    if len(text) > 1200:
        text = text[:1200]
    out_dir = out_dir or settings.MEDIA_DIR
    os.makedirs(out_dir, exist_ok=True)
    chosen = pick_voice(lang, gender, voice) if voice else pick_voice(lang, gender)
    provider = _provider_of(chosen) if voice != "clone" else "clone"

    tmp = tempfile.mktemp(suffix=".mp3")
    rate_s = f"{int((rate - 1) * 100):+d}%"
    pitch_s = f"{int((pitch - 1) * 50):+d}Hz"

    try:
        if provider == "openai":
            await _openai_tts(text, chosen, tmp)
        elif provider == "azure":
            await _azure_tts(text, chosen, tmp, rate, pitch)
        elif provider == "clone":
            await _clone_tts(text, chosen, tmp)
        else:
            await _edge_tts_robust(text, chosen, rate_s, pitch_s, tmp)
    except Exception as first_err:
        # 主通道失败 → 换 edge 默认音色 → 再换备用朗读通道，尽量不让这条语音丢掉
        try:
            if provider != "edge":
                await _edge_tts_robust(text, pick_voice(lang, gender), rate_s, pitch_s, tmp)
            else:
                raise
        except Exception:
            try:
                await _gtts_tts(text, lang, tmp)
            except Exception as e2:
                raise RuntimeError(f"语音合成失败：{first_err} / {e2}")

    dst = os.path.join(out_dir, f"voice_{uuid.uuid4().hex[:12]}.ogg")
    duration = await to_ogg_opus(tmp, dst)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return dst, duration


async def clone_voice(name: str, sample_path: str) -> str:
    """上传 30s-3min 样本做少样本克隆，返回 voice_id。"""
    base = os.getenv("TTS_CLONE_BASE_URL", "").rstrip("/")
    key = os.getenv("TTS_CLONE_API_KEY", "")
    if not base or not key:
        raise RuntimeError("克隆服务未配置（TTS_CLONE_BASE_URL / TTS_CLONE_API_KEY）")
    async with httpx.AsyncClient(timeout=180) as c:
        with open(sample_path, "rb") as f:
            files = {"files[]": (os.path.basename(sample_path), f, "audio/mpeg")}
            data = {"name": name, "description": "zaka clone"}
            r = await c.post(f"{base}/v1/voices/add", data=data, files=files, headers={"xi-api-key": key})
    if r.status_code >= 400:
        raise RuntimeError(f"克隆失败 {r.status_code}: {r.text[:200]}")
    return r.json().get("voice_id", "")
