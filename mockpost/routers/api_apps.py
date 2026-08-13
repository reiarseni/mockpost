"""Internal API /api/apps: app registry (credentials -> identity)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from mockpost.apps import delete_app, get_app_by_name, list_apps, upsert_app

router = APIRouter(prefix="/api/apps", tags=["api"])


class AppPayload(BaseModel):
    name: str
    creds: dict | None = None


@router.get("")
async def api_list_apps():
    return await list_apps()


@router.post("")
async def api_upsert_app(payload: AppPayload):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    return await upsert_app(payload.name.strip(), payload.creds or {})


@router.delete("/{app_id}")
async def api_delete_app(app_id: str):
    await delete_app(app_id)
    return {"ok": True, "deleted": app_id}


@router.get("/by-name/{name}")
async def api_get_app_by_name(name: str):
    app = await get_app_by_name(name)
    if not app:
        raise HTTPException(status_code=404, detail=f"app '{name}' not registered")
    return app
