"""全部数据模型。字段与验收表 F1-F11 一一对应。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(16), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Persona(Base):
    __tablename__ = "personas"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    gender: Mapped[str] = mapped_column(String(16), default="female")
    age: Mapped[int] = mapped_column(Integer, default=26)
    job: Mapped[str] = mapped_column(String(64), default="")
    city: Mapped[str] = mapped_column(String(64), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Phnom_Penh")
    traits: Mapped[list] = mapped_column(JSON, default=list)              # 性格关键词
    tone_level: Mapped[int] = mapped_column(Integer, default=3)           # 1 冷淡 - 5 黏人
    catchphrases: Mapped[list] = mapped_column(JSON, default=list)        # 口头禅
    emoji_habit: Mapped[str] = mapped_column(String(16), default="偶尔")
    sentence_len: Mapped[str] = mapped_column(String(16), default="短句")  # 短句/中等/长句
    paragraph_habit: Mapped[str] = mapped_column(String(16), default="拆条")
    taboo_topics: Mapped[list] = mapped_column(JSON, default=list)
    intimacy_default: Mapped[int] = mapped_column(Integer, default=40)
    default_language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    voice_id: Mapped[str] = mapped_column(String(128), default="")
    voice_ratio: Mapped[int] = mapped_column(Integer, default=20)         # 0-100，语音条概率
    voice_rate: Mapped[float] = mapped_column(Float, default=1.0)
    voice_pitch: Mapped[float] = mapped_column(Float, default=1.0)
    active_hours: Mapped[dict] = mapped_column(JSON, default=lambda: {"start": "09:00", "end": "23:30"})
    background: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PersonaRule(Base):
    """人设自动切换：按联系人或时段。priority 大者优先。"""
    __tablename__ = "persona_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True)
    time_start: Mapped[str] = mapped_column(String(5), default="00:00")
    time_end: Mapped[str] = mapped_column(String(5), default="23:59")
    priority: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(32), index=True)
    api_id: Mapped[str] = mapped_column(String(32), default="")
    api_hash: Mapped[str] = mapped_column(String(64), default="")
    session_enc: Mapped[str | None] = mapped_column(Text, nullable=True)   # Fernet 加密的 StringSession
    device_model: Mapped[str] = mapped_column(String(64), default="Samsung SM-G998B")
    system_version: Mapped[str] = mapped_column(String(32), default="SDK 33")
    app_version: Mapped[str] = mapped_column(String(32), default="10.9.1 (4874)")
    lang_code: Mapped[str] = mapped_column(String(8), default="en")
    fingerprint: Mapped[dict] = mapped_column(JSON, default=dict)         # 稳定设备指纹参数
    proxy: Mapped[dict] = mapped_column(JSON, default=dict)               # {scheme,host,port,user,pass}
    status: Mapped[str] = mapped_column(String(24), default="offline")    # offline/online/waiting_code/waiting_2fa/error
    last_error: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)       # 一键全停开关
    auto_reply: Mapped[bool] = mapped_column(Boolean, default=True)
    proactive_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    warmup_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_limits: Mapped[dict] = mapped_column(JSON, default=dict)         # 覆盖默认三级限速
    tg_self_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tg_self_name: Mapped[str] = mapped_column(String(128), default="")
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    persona: Mapped[Persona | None] = relationship(lazy="selectin")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("account_id", "tg_id", name="uq_contact_account_tg"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    tg_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_name: Mapped[str] = mapped_column(String(128), default="")
    lang: Mapped[str] = mapped_column(String(16), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    blacklist: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)       # 单联系人开关
    mute_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intimacy: Mapped[int] = mapped_column(Integer, default=40)            # 0-100
    interests: Mapped[list] = mapped_column(JSON, default=list)           # [{topic,score,evidence}]
    avoid_topics: Mapped[list] = mapped_column(JSON, default=list)
    emotion_baseline: Mapped[str] = mapped_column(String(32), default="neutral")
    unfinished_topics: Mapped[list] = mapped_column(JSON, default=list)
    key_facts: Mapped[list] = mapped_column(JSON, default=list)
    profile_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_msg_account_contact_time", "account_id", "contact_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    tg_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction: Mapped[str] = mapped_column(String(8))                     # in / out
    source: Mapped[str] = mapped_column(String(8), default="ai")          # ai / manual / contact
    text: Mapped[str] = mapped_column(Text, default="")
    lang: Mapped[str] = mapped_column(String(16), default="")
    msg_type: Mapped[str] = mapped_column(String(16), default="text")    # text / voice / media
    media_path: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)               # persona_id/memory_used/style_refs
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MemoryFact(Base):
    __tablename__ = "memory_facts"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(32), default="fact")     # identity/work/family/preference/appointment/todo
    content: Mapped[str] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StyleProfile(Base):
    __tablename__ = "style_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), unique=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_sentence_len: Mapped[float] = mapped_column(Float, default=0)
    paragraph_ratio: Mapped[float] = mapped_column(Float, default=0)      # 一条消息里出现换行的比例
    emoji_rate: Mapped[float] = mapped_column(Float, default=0)
    catchphrases: Mapped[list] = mapped_column(JSON, default=list)
    punctuation: Mapped[dict] = mapped_column(JSON, default=dict)
    address_style: Mapped[dict] = mapped_column(JSON, default=dict)       # 称呼习惯
    active_hours: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    manual_override: Mapped[dict] = mapped_column(JSON, default=dict)     # 后台手工修正，优先级最高
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StyleSample(Base):
    __tablename__ = "style_samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(16), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProactiveTask(Base):
    __tablename__ = "proactive_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    goal: Mapped[str] = mapped_column(Text, default="")
    persona_id: Mapped[int | None] = mapped_column(ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)            # {tags, last_active_days, limit}
    window_start: Mapped[str] = mapped_column(String(5), default="10:00")
    window_end: Mapped[str] = mapped_column(String(5), default="21:00")
    daily_limit: Mapped[int] = mapped_column(Integer, default=5)
    interval_min: Mapped[int] = mapped_column(Integer, default=180)      # 秒
    interval_max: Mapped[int] = mapped_column(Integer, default=600)
    status: Mapped[str] = mapped_column(String(16), default="paused")    # active/paused/done
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProactiveTarget(Base):
    __tablename__ = "proactive_targets"
    __table_args__ = (UniqueConstraint("task_id", "contact_id", name="uq_target_task_contact"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("proactive_tasks.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending/sent/failed/replied
    opening: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VoiceAsset(Base):
    __tablename__ = "voice_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    lang: Mapped[str] = mapped_column(String(16))                        # zh-CN/zh-TW/nan-TW/en/vi/km
    gender: Mapped[str] = mapped_column(String(16), default="female")
    voice_id: Mapped[str] = mapped_column(String(128))                   # provider 音色 id
    path: Mapped[str] = mapped_column(Text, default="")                  # 克隆样本路径
    is_clone: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str] = mapped_column(String(32), default="")
    object_id: Mapped[str] = mapped_column(String(32), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UsageLog(Base):
    __tablename__ = "usage_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))                        # llm/tts/asr
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ControlCommandLog(Base):
    __tablename__ = "control_commands"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), default="web")       # web / bot
    command: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
