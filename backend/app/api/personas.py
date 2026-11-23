"""人设系统：模板、自定义、复制、导出、一键切换、按联系人或时段自动切换。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import audit, current_user
from ..models import Account, Persona, PersonaRule
from ..schemas import PersonaIn, PersonaRuleIn

router = APIRouter(prefix="/api/personas", tags=["personas"])

FIELDS = [
    "name", "gender", "age", "job", "city", "timezone", "traits", "tone_level",
    "catchphrases", "emoji_habit", "sentence_len", "paragraph_habit", "taboo_topics",
    "intimacy_default", "default_language", "voice_id", "voice_ratio", "voice_rate",
    "voice_pitch", "active_hours", "background",
]


def ser(p: Persona) -> dict:
    return {f: getattr(p, f) for f in FIELDS} | {
        "id": p.id,
        "is_template": p.is_template,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
async def list_personas(user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Persona).order_by(Persona.is_template.desc(), Persona.id))).scalars().all()
    usage = {}
    for a in (await db.execute(select(Account))).scalars().all():
        if a.persona_id:
            usage[a.persona_id] = usage.get(a.persona_id, 0) + 1
    return [ser(p) | {"bound_accounts": usage.get(p.id, 0)} for p in rows]


@router.post("")
async def create_persona(body: PersonaIn, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = Persona(**body.model_dump())
    db.add(p)
    await db.flush()
    await audit(db, actor=user["sub"], action="persona_created", object_type="persona", object_id=p.id,
                detail={"name": p.name})
    await db.commit()
    return ser(p)


@router.patch("/{persona_id}")
async def update_persona(
    persona_id: int, body: PersonaIn, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    p = await db.get(Persona, persona_id)
    if not p:
        raise HTTPException(404, "人设不存在")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    await audit(db, actor=user["sub"], action="persona_updated", object_type="persona", object_id=persona_id)
    await db.commit()
    return ser(p)


@router.post("/{persona_id}/copy")
async def copy_persona(persona_id: int, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Persona, persona_id)
    if not p:
        raise HTTPException(404, "人设不存在")
    data = {f: getattr(p, f) for f in FIELDS if f != "name"}
    clone = Persona(**data, name=f"{p.name} 副本", is_template=False)
    db.add(clone)
    await db.flush()
    await audit(db, actor=user["sub"], action="persona_copied", object_type="persona", object_id=clone.id)
    await db.commit()
    return ser(clone)


@router.get("/{persona_id}/export")
async def export_persona(persona_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    p = await db.get(Persona, persona_id)
    if not p:
        raise HTTPException(404, "人设不存在")
    return {"version": 1, "persona": ser(p)}


@router.post("/import")
async def import_persona(body: dict, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    src = (body or {}).get("persona") or body
    if not isinstance(src, dict) or not src.get("name"):
        raise HTTPException(400, "人设文件格式不对")
    data = {f: src[f] for f in FIELDS if f in src}
    data["name"] = str(data.get("name", "导入人设"))[:60]
    p = Persona(**data, is_template=False)
    db.add(p)
    await db.flush()
    await audit(db, actor=user["sub"], action="persona_imported", object_type="persona", object_id=p.id)
    await db.commit()
    return ser(p)


@router.delete("/{persona_id}")
async def delete_persona(persona_id: int, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Persona, persona_id)
    if not p:
        raise HTTPException(404, "人设不存在")
    if p.is_template:
        raise HTTPException(400, "内置模板不能删除，可以复制一份再改")
    await db.delete(p)
    await audit(db, actor=user["sub"], action="persona_deleted", object_type="persona", object_id=persona_id)
    await db.commit()
    return {"ok": True}


# ---------- 自动切换规则 ----------
@router.get("/rules/list")
async def list_rules(account_id: int | None = None, db: AsyncSession = Depends(get_db), user: dict = Depends(current_user)):
    q = select(PersonaRule).order_by(PersonaRule.priority.desc())
    if account_id:
        q = q.where(PersonaRule.account_id == account_id)
    rows = (await db.execute(q)).scalars().all()
    out = []
    for r in rows:
        p = await db.get(Persona, r.persona_id)
        out.append(
            {
                "id": r.id, "account_id": r.account_id, "persona_id": r.persona_id,
                "persona_name": p.name if p else "", "contact_id": r.contact_id,
                "time_start": r.time_start, "time_end": r.time_end,
                "priority": r.priority, "enabled": r.enabled,
            }
        )
    return out


@router.post("/rules")
async def create_rule(body: PersonaRuleIn, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    r = PersonaRule(**body.model_dump())
    db.add(r)
    await db.flush()
    await audit(db, actor=user["sub"], action="persona_rule_created", object_type="rule", object_id=r.id,
                detail=body.model_dump())
    await db.commit()
    return {"id": r.id}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    r = await db.get(PersonaRule, rule_id)
    if not r:
        raise HTTPException(404, "规则不存在")
    await db.delete(r)
    await audit(db, actor=user["sub"], action="persona_rule_deleted", object_type="rule", object_id=rule_id)
    await db.commit()
    return {"ok": True}
