"""依赖注入与公共工具。"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .core.security import decode_token
from .db import get_db
from .models import AuditLog

bearer = HTTPBearer(auto_error=False)


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录")
    return payload


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


async def audit(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    object_type: str = "",
    object_id: str | int = "",
    detail: dict | None = None,
    ip: str = "",
) -> None:
    db.add(
        AuditLog(
            actor=actor[:64],
            action=action[:64],
            object_type=object_type[:32],
            object_id=str(object_id)[:32],
            detail=detail or {},
            ip=ip[:64],
        )
    )
    await db.flush()
