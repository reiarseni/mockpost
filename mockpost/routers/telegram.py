"""Telegram Bot API emulation (subset) + inbound message simulation."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mockpost.apps import resolve_app
from mockpost.request_ctx import get_app_id, get_test_id
from mockpost.store import insert_message, register_webhook
from mockpost.webhooks import deliver_to_app_webhooks

router = APIRouter(prefix="/telegram", tags=["telegram"])


class SendMessage(BaseModel):
    chat_id: int | str
    text: str
    parse_mode: str | None = None
    reply_markup: dict | None = None


class ClientMessage(BaseModel):
    chat_id: int | str
    text: str
    from_user: str | None = None


@router.post("/bot{token}/sendMessage")
async def send_message(token: str, payload: SendMessage, request: Request):
    body = payload.text
    if payload.reply_markup:
        body = json.dumps({"text": payload.text, "reply_markup": payload.reply_markup}, ensure_ascii=False)
    app = await resolve_app("telegram", token)
    msg_id = await insert_message(
        "telegram", "outbound", body,
        sender=f"bot:{token}", recipient=str(payload.chat_id),
        raw_payload=payload.model_dump(), status="received",
        test_id=get_test_id(request), app_id=app["id"] if app else None,
    )
    return {"ok": True, "result": {"message_id": 1, "chat": {"id": payload.chat_id}, "text": payload.text}}


@router.post("/bot{token}/sendPhoto")
async def send_photo(token: str, request: Request):
    data = await request.form()
    chat_id = data.get("chat_id")
    caption = data.get("caption", "")
    photo = data.get("photo", "")
    app = await resolve_app("telegram", token)
    msg_id = await insert_message(
        "telegram", "outbound", caption or str(photo)[:80],
        sender=f"bot:{token}", recipient=str(chat_id),
        raw_payload={"chat_id": chat_id, "caption": caption, "photo": str(photo)[:200]},
        status="received", test_id=get_test_id(request), app_id=app["id"] if app else None,
    )
    return {"ok": True, "result": {"message_id": 2, "chat": {"id": chat_id}, "caption": caption}}


@router.get("/bot{token}/getUpdates")
async def get_updates(token: str, request: Request):
    """Subset replica: returns the simulated inbound messages of that bot."""
    msgs = await _get_bot_messages(token, request)
    updates = [
        {"update_id": i + 1, "message": {"message_id": i + 1, "chat": {"id": m["sender"]},
                                         "text": m["body"], "from": {"id": 0, "username": "simulated"}}}
        for i, m in enumerate(msgs)
    ]
    return {"ok": True, "result": updates}


async def _get_bot_messages(token: str, request: Request):
    from mockpost.store import list_messages
    test_id = get_test_id(request)
    msgs = await list_messages(channel="telegram", test_id=test_id, limit=100)
    return [m for m in msgs if m["direction"] == "inbound" and m["sender"] and str(m["sender"]).startswith("chat:")]


@router.post("/bot{token}/setWebhook")
async def set_webhook(token: str, request: Request):
    data = await request.json()
    url = data.get("url")
    if not url:
        return JSONResponse({"ok": False, "error_code": 400, "description": "Bad Request: url is required"}, status_code=400)
    app = await resolve_app("telegram", token)
    await register_webhook("telegram", url, token=token, config={"bot_token": token},
                           app_id=app["id"] if app else None)
    return {"ok": True, "result": True, "description": "Webhook was set"}


@router.post("/client/sendMessage")
async def client_send_message(payload: ClientMessage, request: Request):
    """Simulate an external user sending an inbound message to the app (via the bot webhook).

    The target app is chosen with the X-MockPost-App header (registered app name);
    delivery happens only to that app's webhooks."""
    test_id = get_test_id(request)
    app_id = await get_app_id(request)
    msg_id = await insert_message(
        "telegram", "inbound", payload.text,
        sender=f"chat:{payload.chat_id}", recipient="app",
        raw_payload=payload.model_dump(), status="received", test_id=test_id, app_id=app_id,
    )
    results = await deliver_to_app_webhooks(
        "telegram", "message", {"message": {"chat": {"id": payload.chat_id}, "text": payload.text}},
        test_id=test_id, app_id=app_id,
    )
    return {"ok": True, "message_id": msg_id, "app_id": app_id, "webhooks_delivered": results}
