"""风格档案 + 语音管理（音色目录、试听、克隆）。"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core import style as style_mod
from ..core import tts as ttsmod
from ..db import get_db
from ..deps import audit, current_user
from ..models import Account, StyleProfile, StyleSample, VoiceAsset
from ..schemas import StyleImportIn, StyleOverrideIn, VoicePreviewIn

router = APIRouter(prefix="/api", tags=["style-voice"])


# ---------------- 风格档案 ----------------
@router.get("/style/{account_id}")
async def get_style(account_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    p = (
        await db.execute(select(StyleProfile).where(StyleProfile.account_id == account_id))
    ).scalar_one_or_none()
    n = (
        await db.execute(select(func.count(StyleSample.id)).where(StyleSample.account_id == account_id))
    ).scalar() or 0
    if not p:
        return {"sample_count": n, "avg_sentence_len": 0, "paragraph_ratio": 0, "emoji_rate": 0,
                "catchphrases": [], "punctuation": {}, "address_style": {}, "active_hours": {},
                "summary": "", "manual_override": {}, "updated_at": None}
    return {
        "sample_count": p.sample_count, "avg_sentence_len": p.avg_sentence_len,
        "paragraph_ratio": p.paragraph_ratio, "emoji_rate": p.emoji_rate,
        "catchphrases": p.catchphrases, "punctuation": p.punctuation,
        "address_style": p.address_style, "active_hours": p.active_hours,
        "summary": p.summary, "manual_override": p.manual_override,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "samples_in_db": n,
    }


@router.post("/style/import")
async def import_style(body: StyleImportIn, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    texts = [t.strip() for t in body.raw_text.split("\n") if t.strip()]
    if not texts:
        raise HTTPException(400, "没有可用文本，按行粘贴你自己的历史消息")
    n = await style_mod.import_samples(db, body.account_id, texts)
    prof = await style_mod.rebuild_profile(db, body.account_id)
    await audit(db, actor=user["sub"], action="style_imported", object_type="account",
                object_id=body.account_id, detail={"imported": n})
    await db.commit()
    return {"imported": n, "summary": prof.summary, "catchphrases": prof.catchphrases}


@router.post("/style/{account_id}/pull")
async def pull_style(account_id: int, limit: int = 300, db: AsyncSession = Depends(get_db),
                     user: dict = Depends(current_user)):
    from ..workers.jobs import pull_history_job

    try:
        res = await pull_history_job(account_id, limit)
    except Exception as e:
        raise HTTPException(400, f"拉取失败：{e}")
    await audit(db, actor=user["sub"], action="style_pulled", object_type="account", object_id=account_id,
                detail=res)
    await db.commit()
    return res


@router.post("/style/{account_id}/rebuild")
async def rebuild_style(account_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    prof = await style_mod.rebuild_profile(db, account_id)
    await db.commit()
    return {"summary": prof.summary, "catchphrases": prof.catchphrases}


@router.patch("/style/{account_id}/override")
async def override_style(
    account_id: int, body: StyleOverrideIn, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)
):
    """后台手工修正，立即生效（优先级高于自动分析）。"""
    p = (
        await db.execute(select(StyleProfile).where(StyleProfile.account_id == account_id))
    ).scalar_one_or_none()
    if not p:
        p = StyleProfile(account_id=account_id)
        db.add(p)
    ov = dict(p.manual_override or {})
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            ov[k] = v
    p.manual_override = ov
    await audit(db, actor=user["sub"], action="style_override", object_type="account",
                object_id=account_id, detail=ov)
    await db.commit()
    return {"manual_override": ov}


# ---------------- 语音 ----------------
@router.get("/voice/catalog")
async def voice_catalog(lang: str = "", gender: str = "", user: dict = Depends(current_user)):
    if lang:
        return {lang: ttsmod.voices_for(lang, gender or "female")}
    return ttsmod.VOICE_CATALOG


@router.post("/voice/preview")
async def voice_preview(body: VoicePreviewIn, user: dict = Depends(current_user)):
    try:
        path, dur = await ttsmod.synthesize(
            body.text, lang=body.lang, gender=body.gender, voice=body.voice, rate=body.rate, pitch=body.pitch
        )
    except Exception as e:
        raise HTTPException(400, f"合成失败：{e}")
    return {"url": f"/media/{os.path.basename(path)}", "duration": dur}


@router.post("/voice/clone")
async def voice_clone(
    file: UploadFile = File(...),
    name: str = "克隆音色",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user),
):
    if file.content_type not in ("audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/x-wav",
                                 "audio/webm", "application/octet-stream"):
        raise HTTPException(400, "请上传音频文件（mp3/wav/m4a/ogg），时长 30 秒到 3 分钟")
    os.makedirs(settings.MEDIA_DIR, exist_ok=True)
    dst = os.path.join(settings.MEDIA_DIR, f"sample_{uuid.uuid4().hex[:10]}.mp3")
    with open(dst, "wb") as f:
        f.write(await file.read())
    dur = await ttsmod.probe_duration(dst)
    if dur < 20:
        raise HTTPException(400, f"样本只有 {dur:.0f} 秒，太短了，建议 30 秒 - 3 分钟")
    try:
        voice_id = await ttsmod.clone_voice(name, dst)
    except Exception as e:
        raise HTTPException(400, f"克隆失败：{e}")
    db.add(VoiceAsset(name=name, lang="", gender="", voice_id=voice_id, path=dst, is_clone=True, provider="clone"))
    await audit(db, actor=user["sub"], action="voice_cloned", detail={"name": name, "voice_id": voice_id})
    await db.commit()
    return {"voice_id": voice_id, "duration": dur}


@router.get("/voice/assets")
async def list_assets(db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    rows = (await db.execute(select(VoiceAsset).order_by(VoiceAsset.id.desc()))).scalars().all()
    return [
        {
            "id": a.id, "name": a.name, "lang": a.lang, "gender": a.gender,
            "voice_id": a.voice_id, "is_clone": a.is_clone, "provider": a.provider,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.post("/voice/assets")
async def save_asset(body: dict, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    a = VoiceAsset(
        name=str(body.get("name", ""))[:60], lang=str(body.get("lang", "")), gender=str(body.get("gender", "")),
        voice_id=str(body.get("voice_id", "")), is_clone=bool(body.get("is_clone", False)),
        provider=str(body.get("provider", "edge")),
    )
    if not a.name or not a.voice_id:
        raise HTTPException(400, "名称和音色 ID 都要填")
    db.add(a)
    await db.commit()
    return {"id": a.id}
