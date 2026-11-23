"""应用入口。"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .api import accounts, auth, chats, contacts, personas, proactive, style_voice, system
from .config import settings
from .core import security
from .db import SessionLocal, init_db
from .models import User
from .seed import seed_personas

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")

# 网络层的底层握手日志压到 WARNING，别把启动日志淹掉（出错仍会打印）
for _noisy in ("telethon", "httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


async def _ensure_admin() -> None:
    async with SessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == settings.ADMIN_USERNAME))).scalar_one_or_none()
        if not u:
            db.add(
                User(
                    username=settings.ADMIN_USERNAME,
                    password_hash=security.hash_password(settings.ADMIN_PASSWORD),
                    role="admin",
                )
            )
            await db.commit()
            log.info("已创建管理员 %s", settings.ADMIN_USERNAME)
        added = await seed_personas(db)
        await db.commit()
        if added:
            log.info("已写入 %s 个人设模板", added)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.MEDIA_DIR, exist_ok=True)
    await init_db()
    await _ensure_admin()

    # 自检尽早开跑（不阻塞启动），结果会出现在启动日志里
    from .core.bootcheck import run_selfcheck, start_watchdog

    asyncio.create_task(run_selfcheck(), name="boot-selfcheck")

    from .tg.manager import manager
    from .tg.controlbot import start_control_bot
    from .workers.scheduler import start_scheduler, stop_scheduler

    try:
        await manager.restore_all()
    except Exception as e:
        log.warning("恢复账号失败: %s", e)
    try:
        await start_control_bot()
    except Exception as e:
        log.warning("控制 bot 启动失败: %s", e)

    from .core.bootcheck import start_watchdog

    start_watchdog()
    start_scheduler()

    # 开机自检：把真实环境能力打进日志，便于部署后核对（不含任何密钥内容）
    try:
        import shutil as _sh

        from sqlalchemy import func as _func

        from .core import bins as _bins
        from .models import Account as _Account
        from .models import Persona as _Persona

        async with SessionLocal() as _db:
            _accs = (await _db.execute(select(_func.count(_Account.id)))).scalar() or 0
            _pers = (await _db.execute(select(_func.count(_Persona.id)))).scalar() or 0
        log.info(
            "SELFCHECK model=%s llm_key=%s tg_api=%s ffmpeg=%s tts=%s asr=%s control_bot_token=%s accounts=%s personas=%s",
            settings.LLM_MODEL or "-",
            bool(settings.LLM_API_KEY),
            bool(settings.TG_API_ID and settings.TG_API_HASH),
            bool(_bins.available(settings.FFMPEG_BIN, "ffmpeg")),
            settings.TTS_PROVIDER,
            settings.ASR_BACKEND,
            bool(settings.CONTROL_BOT_TOKEN),
            _accs,
            _pers,
        )
    except Exception as e:
        log.warning("自检日志失败: %s", e)

    log.info("服务已启动")
    yield

    await stop_scheduler()
    from .core.bootcheck import stop_watchdog

    await stop_watchdog()
    from .tg.controlbot import stop_control_bot
    from .tg.manager import manager as m

    await stop_control_bot()
    for aid in list(m.runners.keys()):
        await m.stop_account(aid)


app = FastAPI(title="AI Account Operator", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, accounts.router, personas.router, contacts.router,
          chats.router, proactive.router, style_voice.router, system.router):
    app.include_router(r)

os.makedirs(settings.MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "ai-account-operator", "version": "1.0.0"}


# 前端构建产物：生产环境由 nginx 托管；单进程/托管模式下由后端直接托管
_static_dir = os.getenv(
    "STATIC_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
)
if os.path.isdir(_static_dir):
    from fastapi.responses import FileResponse

    _assets = os.path.join(_static_dir, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """前端是单页应用，深链接刷新也要能打开。"""
        candidate = os.path.join(_static_dir, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_static_dir, "index.html"))
