"""WhatsApp Cloud API emulation (subset) + status/inbound webhooks.

Fidelity notes, mirroring graph.facebook.com:

- The path carries the Graph version the SDK was built for
  (/v17.0/{phone_id}/messages); any version is accepted and the old
  /whatsapp/v1/... keeps working.
- Errors use the Graph envelope: {"error": {"message", "type", "code",
  "fbtrace_id"}}.
- Message ids are `wamid.<base64>`, the shape clients match on.
- Webhook verification is the real GET with hub.mode/hub.verify_token/
  hub.challenge; the POST form stays for existing callers.
"""

from __future__ import annotations

import base64
import os
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from mockpost.apps import resolve_app
from mockpost.config import settings, utcnow
from mockpost.request_ctx import get_app_id, get_test_id
from mockpost.store import insert_message, update_message_status
from mockpost.webhooks import deliver_to_app_webhooks

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


class WaMessage(BaseModel):
    to: str
    text: dict | None = None
    template: dict | None = None
    image: dict | None = None
    document: dict | None = None
    interactive: dict | None = None
    type: str = "text"
    messaging_product: str = "whatsapp"


def graph_error(message: str, code: int = 190, status: int = 401,
                error_type: str = "OAuthException") -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": error_type, "code": code,
                                   "fbtrace_id": uuid.uuid4().hex[:16]}}, status_code=status)


def wamid() -> str:
    return "wamid." + base64.b64encode(os.urandom(24)).decode().rstrip("=")


def summarize(payload: WaMessage) -> str:
    """One readable line per message type, which is what the panel shows."""
    if payload.text:
        return payload.text.get("body", "")
    if payload.template:
        return f"template:{payload.template.get('name', '')}"
    if payload.interactive:
        return (payload.interactive.get("body") or {}).get("text", "") or "interactive"
    for kind in ("image", "document"):
        media = getattr(payload, kind)
        if media:
            return media.get("caption") or f"{kind}:{media.get('link') or media.get('id', '')}"
    return payload.type


@router.post("/v{version}/{phone_id}/messages")
async def send_message(version: str, phone_id: str, payload: WaMessage, request: Request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if settings.strict_auth and not token:
        return graph_error("Invalid OAuth access token - Cannot parse access token")
    if payload.messaging_product != "whatsapp":
        return graph_error("(#100) Param messaging_product must be 'whatsapp'",
                           code=100, status=400, error_type="GraphMethodException")

    app = await resolve_app("whatsapp", phone_id) or await resolve_app("whatsapp", token)
    message_id = wamid()
    await insert_message(
        "whatsapp", "outbound", summarize(payload),
        sender=f"whatsapp:{phone_id}", recipient=payload.to,
        raw_payload=payload.model_dump(exclude_none=True), status="received",
        test_id=get_test_id(request), app_id=app["id"] if app else None,
        meta={"graph_version": f"v{version}", "type": payload.type, "wamid": message_id},
    )
    return {"messaging_product": "whatsapp",
            "contacts": [{"input": payload.to, "wa_id": payload.to}],
            "messages": [{"id": message_id, "message_status": "accepted"}]}


@router.get("/webhook")
async def webhook_verify(request: Request):
    """Real Meta verification handshake: echo hub.challenge as plain text."""
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token"):
        return PlainTextResponse(params.get("hub.challenge", ""))
    return graph_error("The verification token does not match", code=0, status=403)


@router.post("/webhook")
async def webhook_handler(request: Request):
    """The app registers ITS real webhook here (public URL of the test environment)."""
    data = await request.json()
    # Hub challenge sent in the body by some clients
    if "hub.challenge" in data or "hub_mode" in data:
        return {"hub.challenge": data.get("hub.challenge", "challenge_ok")}
    return {"status": "accepted"}


def _value(phone_id: str, **extra) -> dict:
    """The `value` object every Cloud API webhook carries."""
    return {"messaging_product": "whatsapp",
            "metadata": {"display_phone_number": phone_id, "phone_number_id": phone_id},
            **extra}


@router.post("/simulate/status")
async def simulate_status(request: Request):
    """Fire a status event (sent/delivered/read/failed) to the given app."""
    data = await request.json()
    status = data.get("status", "delivered")
    message_id = data.get("message_id", "")
    recipient = data.get("recipient_id", data.get("to", ""))
    phone_id = data.get("phone_number_id", "15550000000")
    test_id = get_test_id(request)
    app_id = await get_app_id(request)
    await update_message_status(message_id, status)
    results = await deliver_to_app_webhooks(
        "whatsapp", "status_update",
        {"object": "whatsapp_business_account",
         "entry": [{"id": phone_id, "changes": [{"field": "messages", "value": _value(
             phone_id, statuses=[{"id": message_id, "status": status,
                                  "timestamp": utcnow(), "recipient_id": recipient}])}]}]},
        test_id=test_id, app_id=app_id,
    )
    return {"ok": True, "app_id": app_id, "webhooks_delivered": results}


@router.post("/simulate/incoming")
async def simulate_incoming(request: Request):
    """Simulate an external user sending an inbound message to the given app (X-MockPost-App)."""
    data = await request.json()
    text = data.get("text", "")
    sender = data.get("from", "sim-user")
    phone_id = data.get("phone_number_id", "15550000000")
    test_id = get_test_id(request)
    app_id = await get_app_id(request)
    msg_id = await insert_message(
        "whatsapp", "inbound", text,
        sender=sender, recipient="app",
        raw_payload=data, status="received", test_id=test_id, app_id=app_id,
    )
    results = await deliver_to_app_webhooks(
        "whatsapp", "incoming_message",
        {"object": "whatsapp_business_account",
         "entry": [{"id": phone_id, "changes": [{"field": "messages", "value": _value(
             phone_id,
             contacts=[{"profile": {"name": data.get("name", "Simulated User")}, "wa_id": sender}],
             messages=[{"from": sender, "id": wamid(), "timestamp": utcnow(),
                        "type": "text", "text": {"body": text}}])}]}]},
        test_id=test_id, app_id=app_id,
    )
    return {"ok": True, "message_id": msg_id, "app_id": app_id, "webhooks_delivered": results}
