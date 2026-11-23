"""认证、加密、审计工具。"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
import pyotp

# passlib 读取 bcrypt 版本号的方式在新版 bcrypt 上会抛告警噪音，先补齐属性
try:  # pragma: no cover
    import bcrypt as _bcrypt

    if not hasattr(_bcrypt, "__about__"):

        class _BcryptAbout:
            __version__ = getattr(_bcrypt, "__version__", "4.2.1")

        _bcrypt.__about__ = _BcryptAbout()  # type: ignore[attr-defined]
except Exception:
    pass

from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from ..config import settings

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------- 密码 ----------
def hash_password(raw: str) -> str:
    return pwd_ctx.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(raw, hashed)
    except Exception:
        return False


def password_strength(raw: str) -> tuple[bool, str]:
    if len(raw) < 10:
        return False, "密码至少 10 位"
    classes = sum(
        bool(re.search(p, raw))
        for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]")
    )
    if classes < 3:
        return False, "密码需包含大写、小写、数字、符号中的至少三类"
    return True, ""


# ---------- JWT ----------
def create_token(username: str, role: str = "admin") -> str:
    payload = {
        "sub": username,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


# ---------- 2FA ----------
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="AI Operator")


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


# ---------- Telegram session 加密 ----------
def _fernet() -> Fernet:
    key = settings.SESSION_ENC_KEY
    if not key:
        # 由 SECRET_KEY 派生，避免明文落库；生产建议单独配置 SESSION_ENC_KEY
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_session(raw: str) -> str:
    return _fernet().encrypt(raw.encode()).decode()


def decrypt_session(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, Exception):
        raise ValueError("会话密钥不匹配，无法解密 session")


# ---------- 杂项 ----------
def mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep * 2:
        return s[:2] + "*" * max(1, len(s) - 2)
    return s[:keep] + "*" * (len(s) - keep * 2) + s[-keep:]
