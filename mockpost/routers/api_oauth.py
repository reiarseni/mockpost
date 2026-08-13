"""Internal API /api/oauth: fake profile and sessions."""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel

from mockpost.db import get_db

router = APIRouter(prefix="/api/oauth", tags=["api"])


class ProfilePayload(BaseModel):
    provider: str  # 'google' | 'github'
    profile: dict


@router.post("/profile")
async def set_profile(payload: ProfilePayload):
    db = get_db()
    cur = await db.execute("SELECT id FROM oauth_sessions WHERE provider=? ORDER BY created_at DESC LIMIT 1",
                           (payload.provider,))
    row = await cur.fetchone()
    if row:
        await db.execute("UPDATE oauth_sessions SET fake_user_profile=? WHERE id=?", (json.dumps(payload.profile), row["id"]))
    else:
        from mockpost.config import settings
        settings.default_oauth_profile[payload.provider] = payload.profile
    await db.commit()
    return {"ok": True, "provider": payload.provider, "profile": payload.profile}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    db = get_db()
    cur = await db.execute("SELECT * FROM oauth_sessions WHERE id=?", (session_id,))
    row = await cur.fetchone()
    if not row:
        return {"error": "not_found", "session_id": session_id}
    d = dict(row)
    d["fake_user_profile"] = json.loads(d["fake_user_profile"])
    return d


@router.get("/sessions")
async def list_sessions(provider: str | None = None):
    db = get_db()
    q = "SELECT * FROM oauth_sessions"
    params: list = []
    if provider:
        q += " WHERE provider=?"
        params.append(provider)
    q += " ORDER BY created_at DESC"
    cur = await db.execute(q, params)
    rows = await cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["fake_user_profile"] = json.loads(d["fake_user_profile"])
        out.append(d)
    return out
