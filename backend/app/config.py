"""全局配置。所有密钥、模型、端点一律走环境变量，代码里不写死任何 key 或模型名。"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 可能被放在 backend/ 或项目根，两种布局都认；用绝对路径，不依赖启动时的工作目录
_HERE = Path(__file__).resolve()
_ENV_FILES = [str(p) for p in (_HERE.parents[1] / ".env", _HERE.parents[2] / ".env") if p.parent.exists()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    # ---- 基础 ----
    APP_NAME: str = "AI Account Operator"
    ENV: Literal["dev", "prod"] = "prod"
    SECRET_KEY: str = "change-me-in-env"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "change-me-in-env"          # 首次启动写入 DB，之后以 DB 为准
    SESSION_ENC_KEY: str = ""                          # Fernet key，Telethon session 加密用
    ACCESS_TOKEN_TTL_MIN: int = 720

    # ---- 数据库 / 队列 ----
    DATABASE_URL: str = "postgresql+asyncpg://op:op@db:5432/operator"
    REDIS_URL: str = "redis://redis:6379/0"
    QUEUE_BACKEND: Literal["redis", "inline"] = "redis"

    # ---- LLM（可配置，不写死）----
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_TEMPERATURE: float = 0.9
    LLM_MAX_TOKENS: int = 700
    LLM_TIMEOUT: int = 60
    LLM_JSON_MODEL: str = ""          # 抽取类任务可单独配小模型，留空用 LLM_MODEL
    LLM_FALLBACK_MODELS: str = ""     # 逗号分隔的备用模型：主模型额度用完/下线时自动降级
    # 多厂商轮换链（JSON 数组）：[{"name","base_url","api_key","models":[],"extra":{}}]
    # 按顺序尝试，前一家额度用完/限流/模型下线自动换下一家
    LLM_PROVIDERS: str = ""

    # ---- 语音 ----
    TTS_PROVIDER: str = "edge"        # edge | openai | azure | google
    TTS_OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    TTS_OPENAI_API_KEY: str = ""
    TTS_OPENAI_MODEL: str = ""
    TTS_AZURE_KEY: str = ""
    TTS_AZURE_REGION: str = ""
    TTS_GOOGLE_CREDENTIALS_JSON: str = ""
    TTS_TIMEOUT: int = 60

    ASR_BACKEND: Literal["faster-whisper", "openai", "gemini", "groq"] = "faster-whisper"
    ASR_MODEL: str = "large-v3"
    ASR_GEMINI_API_KEY: str = ""
    ASR_GEMINI_MODEL: str = "gemini-3-flash-preview"
    # Groq Whisper：免费额度大、快，收到语音条优先走这里
    ASR_GROQ_API_KEY: str = ""
    ASR_GROQ_MODEL: str = "whisper-large-v3"
    ASR_GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    ASR_DEVICE: str = "cpu"
    ASR_COMPUTE_TYPE: str = "int8"
    ASR_OPENAI_BASE_URL: str = ""
    ASR_OPENAI_API_KEY: str = ""
    ASR_OPENAI_MODEL: str = "whisper-1"

    FFPROBE_BIN: str = "ffprobe"
    FFMPEG_BIN: str = "ffmpeg"
    MEDIA_DIR: str = "/data/media"
    SESSION_DIR: str = "/data/sessions"

    # ---- 默认限速（后台可改，落 Setting 表）----
    RL_MINUTE: int = 6
    RL_HOUR: int = 40
    RL_DAY: int = 150
    WARMUP_QUIET_HOURS: int = 36
    WARMUP_WEEK1_DAILY: int = 8

    # ---- Telegram API（平台应用凭据，用户也可在后台为单账号覆盖）----
    TG_API_ID: str = ""
    TG_API_HASH: str = ""

    # ---- 控制 bot（BotFather token，也可在后台系统设置里改）----
    CONTROL_BOT_TOKEN: str = ""
    # 控制者 Telegram 数字 id，逗号分隔；设了就固定管理员，不再"谁先说谁是主人"
    CONTROL_ADMIN_IDS: str = ""

    CORS_ORIGINS: str = "*"
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
