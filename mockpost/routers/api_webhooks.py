"""Internal API /api/webhooks: register, list, trigger, delete + delivery history."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from mockpost.apps import get_app_by_name
from mockpost.request_ctx import get_test_id
from mockpost.store import WEBHOOK_CHANNELS, delete_webhook, get_webhook, list_webhooks, register_webhook
from mockpost.webhooks import deliver_webhook, list_webhook_deliveries

router = APIRouter(prefix="/api/webhooks", tags=["api"])


class RegisterPayload(BaseModel):
    channel: str
    target_url: str
    token: str | None = None
    config: dict | None = None
    app: str | None = None  # nombre de app registrada (opcional)


class TriggerPayload(BaseModel):
    event_type: str = "test"
    payload: dict | None = None


async def _resolve_app_id(payload: RegisterPayload, request: Request) -> str | None:
    """App del webhook: por nombre en el payload, o header X-MockPost-App."""
    name = payload.app or request.headers.get("X-MockPost-App")
    if not name:
        return None
    app = await get_app_by_name(name)
    if not app:
        raise HTTPException(status_code=404, detail=f"app '{name}' not registered (use POST /api/apps)")
    return app["id"]


@router.post("")
async def api_register(payload: RegisterPayload, request: Request):
    if payload.channel not in WEBHOOK_CHANNELS:
        raise HTTPException(status_code=400,
                            detail=f"channel '{payload.channel}' does not support webhooks back to the app; "
                                   f"valid: {', '.join(WEBHOOK_CHANNELS)}")
    app_id = await _resolve_app_id(payload, request)
    wid = await register_webhook(payload.channel, payload.target_url, token=payload.token,
                                 config=payload.config, app_id=app_id)
    return {"id": wid, "ok": True, "app_id": app_id}


@router.get("")
async def api_list(channel: str | None = None, app: str | None = None):
    app_id = None
    if app:
        a = await get_app_by_name(app)
        if a:
            app_id = a["id"]
    return await list_webhooks(channel, app_id)


@router.post("/{webhook_id}/trigger")
async def api_trigger(webhook_id: str, payload: TriggerPayload, request: Request):
    wh = await get_webhook(webhook_id)
    if not wh:
        return {"error": "not_found", "webhook_id": webhook_id}
    test_id = get_test_id(request)
    result = await deliver_webhook(wh["channel"], wh["target_url"], payload.event_type,
                                   payload.payload or {}, test_id=test_id, app_id=wh["app_id"])
    return result


@router.delete("/{webhook_id}")
async def api_delete(webhook_id: str):
    await delete_webhook(webhook_id)
    return {"ok": True, "deleted": webhook_id}


@router.get("/deliveries")
async def api_deliveries(request: Request, channel: str | None = None, app: str | None = None,
                         limit: int = 50):
    """Delivery history: what each app returned (code + body), even when it was down."""
    test_id = get_test_id(request)
    app_id = None
    if app:
        a = await get_app_by_name(app)
        if a:
            app_id = a["id"]
    return await list_webhook_deliveries(app_id=app_id, channel=channel, test_id=test_id, limit=limit)
