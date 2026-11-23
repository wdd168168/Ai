"""请求/响应模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str
    totp: str = ""


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    totp_enabled: bool = False


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


class AccountIn(BaseModel):
    label: str = ""
    phone: str
    api_id: str = ""
    api_hash: str = ""
    device_model: str = "Samsung SM-G998B"
    system_version: str = "SDK 33"
    app_version: str = "10.9.1 (4874)"
    lang_code: str = "en"
    proxy: dict = Field(default_factory=dict)
    persona_id: int | None = None
    rate_limits: dict = Field(default_factory=dict)


class AccountUpdate(BaseModel):
    label: str | None = None
    persona_id: int | None = None
    enabled: bool | None = None
    ai_enabled: bool | None = None
    auto_reply: bool | None = None
    proactive_enabled: bool | None = None
    proxy: dict | None = None
    rate_limits: dict | None = None
    device_model: str | None = None
    system_version: str | None = None
    app_version: str | None = None


class VerifyCodeIn(BaseModel):
    code: str
    password: str = ""


class PersonaIn(BaseModel):
    name: str
    gender: str = "female"
    age: int = 26
    job: str = ""
    city: str = ""
    timezone: str = "Asia/Phnom_Penh"
    traits: list[str] = Field(default_factory=list)
    tone_level: int = 3
    catchphrases: list[str] = Field(default_factory=list)
    emoji_habit: str = "偶尔"
    sentence_len: str = "短句"
    paragraph_habit: str = "拆条"
    taboo_topics: list[str] = Field(default_factory=list)
    intimacy_default: int = 40
    default_language: str = "zh-CN"
    voice_id: str = ""
    voice_ratio: int = 20
    voice_rate: float = 1.0
    voice_pitch: float = 1.0
    active_hours: dict = Field(default_factory=lambda: {"start": "09:00", "end": "23:30"})
    background: str = ""


class PersonaRuleIn(BaseModel):
    account_id: int
    persona_id: int
    contact_id: int | None = None
    time_start: str = "00:00"
    time_end: str = "23:59"
    priority: int = 10
    enabled: bool = True


class ContactUpdate(BaseModel):
    note: str | None = None
    tags: list[str] | None = None
    blacklist: bool | None = None
    ai_enabled: bool | None = None
    mute_minutes: int | None = None
    intimacy: int | None = None


class ManualMessage(BaseModel):
    text: str


class ProactiveTaskIn(BaseModel):
    account_id: int
    name: str
    goal: str = ""
    persona_id: int | None = None
    filters: dict = Field(default_factory=dict)
    window_start: str = "10:00"
    window_end: str = "21:00"
    daily_limit: int = 5
    interval_min: int = 180
    interval_max: int = 600
    status: str = "paused"


class StyleImportIn(BaseModel):
    account_id: int
    raw_text: str = ""


class StyleOverrideIn(BaseModel):
    avg_sentence_len: float | None = None
    catchphrases: list[str] | None = None
    emoji_rate: float | None = None


class VoicePreviewIn(BaseModel):
    text: str
    lang: str = "zh-CN"
    gender: str = "female"
    voice: str = ""
    rate: float = 1.0
    pitch: float = 1.0


class LLMConfigIn(BaseModel):
    base_url: str
    api_key: str = ""
    model: str
    json_model: str = ""
    temperature: float = 0.9
    max_tokens: int = 700
    timeout: int = 60


class ChatConfigIn(BaseModel):
    lang_mode: str = "follow"
    fixed_lang: str = "zh-CN"
    manual_yield_minutes: int = 20
    reply_in_offhours: bool = False


class ControlBotIn(BaseModel):
    token: str = ""
    admin_ids: list[int] = Field(default_factory=list)


class AuditOut(BaseModel):
    id: int
    actor: str
    action: str
    object_type: str
    object_id: str
    detail: dict
    created_at: datetime
