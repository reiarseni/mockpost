"""WhatsApp Cloud API emulation (subset) + status/inbound webhooks."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from mockpost.apps import resolve_app
from mockpost.request_ctx import get_app_id, get_test_id
from mockpost.store import insert_message, update_message_status
from mockpost.webhooks import deliver_to_app_webhooks

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


class WaMessage(BaseModel):
    to: str
    text: dict | None = None
    type: str = "text"
    messaging_product: str = "whatsapp"


@router.post("/v1/{phone_id}/messages")
async def send_message(phone_id: str, payload: WaMessage, request: Request):
    text = ""
    if payload.text:
        text = payload.text.get("body", "")
    app = await resolve_app("whatsapp", phone_id)
    msg_id = await insert_message(
        "whatsapp", "outbound", text,
        sender=f"whatsapp:{phone_id}", recipient=payload.to,
        raw_payload=payload.model_dump(), status="received",
        test_id=get_test_id(request), app_id=app["id"] if app else None,
    )
    return {"messaging_product": "whatsapp", "contacts": [{"input": payload.to, "wa_id": payload.to}],
            "messages": [{"id": msg_id}]}


@router.post("/webhook")
async def webhook_handler(request: Request):
    """The app registers ITS real webhook here (public URL of the test environment)."""
    data = await request.json()
    # Hub challenge (Meta webhook verification)
    if "hub.challenge" in data or "hub_mode" in data:
        return {"hub.challenge": data.get("hub.challenge", "challenge_ok")}
    return {"status": "accepted"}


@router.post("/simulate/status")
async def simulate_status(request: Request):
    """Fire a status event (sent/delivered/read/failed) to the given app."""
    data = await request.json()
    status = data.get("status", "delivered")
    test_id = get_test_id(request)
    app_id = await get_app_id(request)
    await update_message_status(data.get("message_id", ""), status)
    results = await deliver_to_app_webhooks(
        "whatsapp", "status_update",
        {"entry": [{"changes": [{"value": {"statuses": [{"status": status, "id": data.get("message_id")}]}}]}]},
        test_id=test_id, app_id=app_id,
    )
    return {"ok": True, "app_id": app_id, "webhooks_delivered": results}


@router.post("/simulate/incoming")
async def simulate_incoming(request: Request):
    """Simulate an external user sending an inbound message to the given app (X-MockPost-App)."""
    data = await request.json()
    test_id = get_test_id(request)
    app_id = await get_app_id(request)
    msg_id = await insert_message(
        "whatsapp", "inbound", data.get("text", ""),
        sender=data.get("from", "sim-user"), recipient="app",
        raw_payload=data, status="received", test_id=test_id, app_id=app_id,
    )
    results = await deliver_to_app_webhooks(
        "whatsapp", "incoming_message",
        {"entry": [{"changes": [{"value": {"messages": [{"from": data.get("from"), "text": {"body": data.get("text", "")}}]}}]}]},
        test_id=test_id, app_id=app_id,
    )
    return {"ok": True, "message_id": msg_id, "app_id": app_id, "webhooks_delivered": results}
