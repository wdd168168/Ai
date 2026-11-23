"""ASR：收到语音条自动转文字后进入上下文。支持本地 faster-whisper 或 OpenAI 兼容接口。"""
from __future__ import annotations

import os

import httpx

from ..config import settings

_model = None


def _load_whisper():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            settings.ASR_MODEL, device=settings.ASR_DEVICE, compute_type=settings.ASR_COMPUTE_TYPE
        )
    return _model


async def _transcribe_with(backend: str, path: str, lang_hint: str = "") -> str:
    """用指定后端转写一次。"""
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    if backend == "openai":
        base = settings.ASR_OPENAI_BASE_URL or "https://api.openai.com/v1"
        if not settings.ASR_OPENAI_API_KEY:
            raise RuntimeError("未配置 ASR_OPENAI_API_KEY")
        async with httpx.AsyncClient(timeout=180) as c:
            with open(path, "rb") as f:
                files = {"file": (os.path.basename(path), f, "audio/ogg")}
                data = {"model": settings.ASR_OPENAI_MODEL}
                if lang_hint:
                    data["language"] = lang_hint.split("-")[0]
                r = await c.post(
                    f"{base.rstrip('/')}/audio/transcriptions",
                    files=files,
                    data=data,
                    headers={"Authorization": f"Bearer {settings.ASR_OPENAI_API_KEY}"},
                )
        if r.status_code >= 400:
            raise RuntimeError(f"ASR {r.status_code}: {r.text[:200]}")
        return (r.json().get("text") or "").strip()

    if backend == "groq":
        key = (settings.ASR_GROQ_API_KEY or "").strip()
        if not key:
            raise RuntimeError("未配置 ASR_GROQ_API_KEY")
        base = (settings.ASR_GROQ_BASE_URL or "https://api.groq.com/openai/v1").rstrip("/")
        async with httpx.AsyncClient(timeout=180) as c:
            with open(path, "rb") as f:
                files = {"file": (os.path.basename(path), f, "audio/ogg")}
                data = {"model": settings.ASR_GROQ_MODEL or "whisper-large-v3", "response_format": "json"}
                if lang_hint:
                    data["language"] = lang_hint.split("-")[0]
                r = await c.post(
                    f"{base}/audio/transcriptions",
                    files=files,
                    data=data,
                    headers={"Authorization": f"Bearer {key}"},
                )
        if r.status_code >= 400:
            raise RuntimeError(f"ASR {r.status_code}: {r.text[:200]}")
        return (r.json().get("text") or "").strip()

    if backend == "gemini":
        # 用大模型的多模态能力直接听音频，无需本地 whisper、无需额外 key
        import base64

        key = (settings.ASR_GEMINI_API_KEY or settings.LLM_API_KEY or "").strip()
        if not key:
            raise RuntimeError("未配置 ASR_GEMINI_API_KEY")
        ext = os.path.splitext(path)[1].lower()
        mime = {
            ".ogg": "audio/ogg",
            ".oga": "audio/ogg",
            ".opus": "audio/ogg",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".flac": "audio/flac",
        }.get(ext, "audio/ogg")
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        model = settings.ASR_GEMINI_MODEL or "gemini-3-flash-preview"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "逐字转写这段语音的内容，保持原本使用的语言和口语用词，"
                                "不要翻译、不要总结、不要加解释，只输出转写文字。"
                            )
                        },
                        {"inline_data": {"mime_type": mime, "data": b64}},
                    ]
                }
            ]
        }
        models = [model] + [m for m in ("gemini-flash-lite-latest",) if m != model]
        r = None
        async with httpx.AsyncClient(timeout=180) as c:
            for m in models:
                r = await c.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                    json=payload,
                    headers={"x-goog-api-key": key},
                )
                if r.status_code < 400:
                    model = m
                    break
                if r.status_code not in (404, 429):
                    break
        if r is None or r.status_code >= 400:
            raise RuntimeError(f"ASR {r.status_code if r is not None else '-'}: {r.text[:200] if r is not None else ''}")
        j = r.json()
        try:
            parts = j["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            raise RuntimeError("ASR 返回格式异常")
        return "".join(p.get("text", "") for p in parts).strip()

    # 本地 whisper（CPU 上阻塞，放线程池）
    import asyncio

    def _run() -> str:
        model = _load_whisper()
        segments, _info = model.transcribe(path, language=(lang_hint.split("-")[0] or None), vad_filter=True)
        return "".join(s.text for s in segments).strip()

    return await asyncio.to_thread(_run)


async def transcribe(path: str, lang_hint: str = "") -> str:
    """按可用性依次尝试：groq whisper → 配置的后端 → gemini 多模态 → openai。

    返回转写文本；全部失败才抛异常，由调用方决定是否放过这条语音。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    order: list[str] = []
    if (settings.ASR_GROQ_API_KEY or "").strip():
        order.append("groq")
    order.append(settings.ASR_BACKEND)
    if (settings.ASR_GEMINI_API_KEY or settings.LLM_API_KEY or "").strip():
        order.append("gemini")
    if (settings.ASR_OPENAI_API_KEY or "").strip():
        order.append("openai")

    tried: list[str] = []
    last = ""
    for backend in order:
        if backend in tried:
            continue
        tried.append(backend)
        try:
            text = await _transcribe_with(backend, path, lang_hint)
            if text:
                return text
            last = f"{backend}: 空结果"
        except Exception as e:  # 换下一个后端
            last = f"{backend}: {type(e).__name__}: {str(e)[:150]}"
    raise RuntimeError(last or "没有可用的语音转写后端")
