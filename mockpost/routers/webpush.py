"""Web Push: subscriptions + send with real VAPID validation (py_vapid)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mockpost.db import get_db
from mockpost.request_ctx import get_test_id
from mockpost.signing import verify_vapid, vapid_public_key_b64
from mockpost.store import insert_message

router = APIRouter(prefix="/webpush", tags=["webpush"])


class Subscription(BaseModel):
    endpoint: str
    keys: dict  # {p256dh, auth}


class PushPayload(BaseModel):
    subscription: Subscription
    payload: str | None = None
    ttl: int = 60
    topic: str | None = None


@router.post("/subscribe")
async def subscribe(sub: Subscription, request: Request):
    db = get_db()
    sub_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO webpush_subscriptions (id, endpoint, p256dh, auth, vapid_public_key, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (sub_id, sub.endpoint, sub.keys.get("p256dh", ""), sub.keys.get("auth", ""), vapid_public_key_b64()),
    )
    await db.commit()
    return {"id": sub_id, "endpoint": sub.endpoint, "vapid_public_key": vapid_public_key_b64()}


@router.post("/send")
async def send(payload: PushPayload, request: Request):
    auth = request.headers.get("Authorization", "")
    audience = f"{request.base_url.scheme}://{request.base_url.netloc}"
    if not verify_vapid(auth, audience):
        return JSONResponse({"ok": False, "error": "Unauthorized: invalid VAPID signature"},
                            status_code=401)
    msg_id = await insert_message(
        "webpush", "outbound", payload.payload or "",
        sender=audience, recipient=payload.subscription.endpoint,
        raw_payload=payload.model_dump(), status="received",
        test_id=get_test_id(request),
    )
    return {"ok": True, "message_id": msg_id, "accepted": True}
