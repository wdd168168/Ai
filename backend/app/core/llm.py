"""模型层：完全可配置（base_url + api_key + model），不写死任何厂商或型号。

支持任何 OpenAI 兼容的 /chat/completions 端点（自建网关、各家云、本地 vLLM 均可）。
支持**多厂商轮换链**：一个厂商额度用完 / 限流 / 模型下线，自动换到下一家、下一个模型，
不会因为某一家挂掉就哑巴。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Setting

SETTING_KEY = "llm_config"


@dataclass
class Provider:
    """一个厂商（或一个自建网关）的一路配置。"""

    name: str
    base_url: str
    api_key: str
    models: list[str] = field(default_factory=list)
    json_models: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    timeout: int = 60
    temperature: float = 0.9
    max_tokens: int = 700

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    json_model: str = ""
    temperature: float = 0.9
    max_tokens: int = 700
    timeout: int = 60
    fallback_models: list[str] = field(default_factory=list)
    providers: list[Provider] = field(default_factory=list)

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def chain(self, json_mode: bool) -> list[tuple[Provider, str]]:
        """按优先级排出「厂商 × 模型」的尝试顺序。"""
        out: list[tuple[Provider, str]] = []
        for p in self.providers:
            models = (p.json_models or p.models) if json_mode else p.models
            if not models:
                models = [self.model]
            for m in models:
                if m and (p, m) not in out:
                    out.append((p, m))
        if not out:
            # 没配轮换链时退化成单厂商 + 备用模型名
            single = Provider(
                name="default",
                base_url=self.base_url,
                api_key=self.api_key,
                models=[self.model],
                timeout=self.timeout,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            primary = self.json_model if (json_mode and self.json_model) else self.model
            out.append((single, primary))
            for m in self.fallback_models:
                if m and m != primary:
                    out.append((single, m))
        return out


class LLMError(RuntimeError):
    pass


def _parse_models(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _parse_providers(raw, cfg: "LLMConfig") -> list[Provider]:
    """LLM_PROVIDERS 是一段 JSON 数组；格式坏掉就当没配。"""
    if not raw:
        return []
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return []
    if not isinstance(data, list):
        return []
    out: list[Provider] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        base = str(item.get("base_url") or "").strip()
        models = _parse_models(item.get("models") or item.get("model"))
        if not base or not models:
            continue
        out.append(
            Provider(
                name=str(item.get("name") or f"p{i + 1}"),
                base_url=base,
                api_key=str(item.get("api_key") or "").strip(),
                models=models,
                json_models=_parse_models(item.get("json_models")),
                extra=item.get("extra") if isinstance(item.get("extra"), dict) else {},
                timeout=int(item.get("timeout") or cfg.timeout),
                temperature=float(item.get("temperature") or cfg.temperature),
                max_tokens=int(item.get("max_tokens") or cfg.max_tokens),
            )
        )
    return out


async def load_config(db: AsyncSession) -> LLMConfig:
    row = await db.get(Setting, SETTING_KEY)
    data = (row.value if row else {}) or {}
    cfg = LLMConfig(
        base_url=data.get("base_url") or settings.LLM_BASE_URL,
        api_key=data.get("api_key") or settings.LLM_API_KEY,
        model=data.get("model") or settings.LLM_MODEL,
        json_model=data.get("json_model") or settings.LLM_JSON_MODEL,
        temperature=float(data.get("temperature", settings.LLM_TEMPERATURE)),
        max_tokens=int(data.get("max_tokens", settings.LLM_MAX_TOKENS)),
        timeout=int(data.get("timeout", settings.LLM_TIMEOUT)),
        fallback_models=_parse_models(
            data.get("fallback_models") or settings.LLM_FALLBACK_MODELS
        ),
    )
    # 轮换链优先用环境变量里的配置（部署时以 .env 为准），后台显式改过才覆盖
    cfg.providers = _parse_providers(settings.LLM_PROVIDERS, cfg) or _parse_providers(
        data.get("providers"), cfg
    )
    return cfg


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    return m.group(1) if m else t


def _extract_json(text: str) -> Any:
    t = _strip_code_fence(text)
    try:
        return json.loads(t)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        end = t.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except Exception:
                continue
    raise LLMError("模型返回的不是合法 JSON")


_REASONING_LEAK = re.compile(r"^\s*(思考|分析|让我|先想|用户说|We need|I need|The user)\b", re.I)


def _clean(text: str) -> str:
    """去掉模型把思考过程写进正文的情况（会让聊天像念稿）。"""
    t = (text or "").strip()
    if not t:
        return t
    # 明确的思考段落：以「思考」开头且后面还有正文，砍掉前段
    for marker in ("\n\n", "\n"):
        head, sep, tail = t.partition(marker)
        if sep and _REASONING_LEAK.match(head) and len(head) > 60 and tail.strip():
            t = tail.strip()
            break
    return t.strip()


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        if not cfg.providers and not (cfg.base_url and cfg.model):
            raise LLMError("模型未配置：请在系统设置里填写 base_url / api_key / model")
        self.cfg = cfg

    async def chat(
        self,
        messages: list[dict],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cfg: LLMConfig | None = None,
    ) -> tuple[str, dict]:
        cfg = cfg or self.cfg
        chain = cfg.chain(json_mode)
        errors: list[str] = []
        for idx, (provider, model) in enumerate(chain):
            try:
                return await self._chat_one(
                    provider=provider,
                    payload_model=model,
                    messages=messages,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except LLMError as e:
                errors.append(f"{provider.name}/{model}: {e}")
                continue
        raise LLMError("所有模型都不可用 → " + " ｜ ".join(errors[-3:]) if errors else "模型调用失败")

    async def _chat_one(
        self,
        *,
        provider: Provider,
        payload_model: str,
        messages: list[dict],
        json_mode: bool,
        temperature: float | None,
        max_tokens: int | None,
    ) -> tuple[str, dict]:
        payload: dict[str, Any] = {
            "model": payload_model,
            "messages": messages,
            "temperature": provider.temperature if temperature is None else temperature,
            "max_tokens": provider.max_tokens if max_tokens is None else max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        for k, v in (provider.extra or {}).items():
            payload[k] = v

        headers = {"Content-Type": "application/json"}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"

        last_err = ""
        for attempt in range(2):
            started = time.time()
            try:
                async with httpx.AsyncClient(timeout=provider.timeout) as client:
                    resp = await client.post(provider.endpoint, json=payload, headers=headers)
                elapsed = int((time.time() - started) * 1000)
                if resp.status_code >= 400:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    # 4xx（除 429）换下家，不原地重试
                    if 400 <= resp.status_code < 500 and resp.status_code != 429:
                        raise LLMError(last_err)
                else:
                    data = resp.json()
                    choice = (data.get("choices") or [{}])[0]
                    text = _clean((choice.get("message") or {}).get("content") or "")
                    if not text and (choice.get("message") or {}).get("reasoning"):
                        # 思考吃满额度、正文空 → 换下家，别回空消息
                        last_err = "空回复（思考占满额度）"
                        continue
                    usage = data.get("usage") or {}
                    return text, {
                        "model": f"{provider.name}:{payload_model}",
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "elapsed_ms": elapsed,
                    }
            except LLMError:
                raise
            except Exception as e:  # 网络/超时
                last_err = f"{type(e).__name__}: {e}"
            await asyncio.sleep(0.8)
        raise LLMError(last_err or "模型调用失败")

    async def chat_json(
        self, messages: list[dict], *, temperature: float = 0.2, max_tokens: int = 900
    ) -> tuple[Any, dict]:
        text, usage = await self.chat(
            messages, json_mode=True, temperature=temperature, max_tokens=max_tokens
        )
        return _extract_json(text), usage


async def get_client(db: AsyncSession) -> tuple[LLMClient, LLMConfig]:
    cfg = await load_config(db)
    return LLMClient(cfg), cfg


async def log_usage(
    db: AsyncSession,
    *,
    account_id: int | None,
    kind: str,
    usage: dict,
    ok: bool = True,
    error: str = "",
    chars: int = 0,
) -> None:
    from ..models import UsageLog

    db.add(
        UsageLog(
            account_id=account_id,
            kind=kind,
            model=str(usage.get("model", ""))[:64],
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            chars=chars,
            elapsed_ms=int(usage.get("elapsed_ms", 0) or 0),
            ok=ok,
            error=error[:500],
        )
    )
