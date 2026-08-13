"""Telegram Bot API emulation (subset) + inbound message simulation.

Fidelity notes, all mirroring api.telegram.org:

- Every method answers on GET and POST, and reads its parameters from JSON,
  form-urlencoded, multipart or the query string, exactly like the real API.
  Clients differ: python-telegram-bot sends JSON, most Python/PHP snippets
  send form-urlencoded, file uploads use multipart.
- Responses always use the real envelope: {"ok": true, "result": ...} or
  {"ok": false, "error_code": N, "description": "..."}, with the HTTP status
  matching error_code.
- Message objects carry message_id, from, chat, date and the content field of
  the method, so a client parsing the response finds what it expects.
"""

from __future__ import annotations

import json
import re
import time
from itertools import count
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mockpost.apps import resolve_app
from mockpost.config import settings
from mockpost.db import get_db
from mockpost.request_ctx import get_app_id, get_test_id
from mockpost.store import insert_message, register_webhook
from mockpost.webhooks import deliver_to_app_webhooks

router = APIRouter(prefix="/telegram", tags=["telegram"])

# Real bot tokens look like 123456789:AAH... (35 chars after the colon).
TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{35}$")

_message_ids = count(1000)


class ClientMessage(BaseModel):
    chat_id: int | str
    text: str
    from_user: str | None = None


def error(code: int, description: str) -> JSONResponse:
    """Real Bot API error envelope, with the HTTP status matching error_code."""
    return JSONResponse({"ok": False, "error_code": code, "description": description},
                        status_code=code)


def bot_user(token: str) -> dict:
    bot_id_part = token.split(":")[0]
    bot_id = int(bot_id_part) if bot_id_part.isdigit() else 424242
    return {"id": bot_id, "is_bot": True, "first_name": "MockPost Bot",
            "username": "mockpost_bot"}


def chat_of(chat_id: Any) -> dict:
    """Negative numeric ids are groups in Telegram, @strings are channels."""
    if isinstance(chat_id, str) and chat_id.startswith("@"):
        return {"id": chat_id, "type": "channel", "username": chat_id.lstrip("@")}
    try:
        numeric = int(chat_id)
    except (TypeError, ValueError):
        return {"id": chat_id, "type": "private"}
    return {"id": numeric, "type": "supergroup" if numeric < 0 else "private"}


def message_object(token: str, chat_id: Any, **content) -> dict:
    return {"message_id": next(_message_ids), "from": bot_user(token),
            "chat": chat_of(chat_id), "date": int(time.time()), **content}


async def read_params(request: Request) -> dict:
    """Parameters from JSON, form-urlencoded, multipart or query string."""
    params: dict[str, Any] = dict(request.query_params)
    content_type = (request.headers.get("Content-Type") or "").split(";")[0].strip()
    if content_type == "application/json":
        try:
            body = await request.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            params.update(body)
        return params
    if content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
        form = await request.form()
        for key, value in form.multi_items():
            params[key] = value if isinstance(value, str) else getattr(value, "filename", str(value))
        return params
    raw = await request.body()
    if raw:
        # Unknown or missing Content-Type: the real API still parses a JSON body.
        try:
            body = json.loads(raw)
            if isinstance(body, dict):
                params.update(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return params


async def capture(token: str, request: Request, chat_id: Any, body: str, payload: dict) -> str:
    app = await resolve_app("telegram", token)
    return await insert_message(
        "telegram", "outbound", body,
        sender=f"bot:{token}", recipient=str(chat_id),
        raw_payload=payload, status="received",
        test_id=get_test_id(request), app_id=app["id"] if app else None,
    )


# --- methods -------------------------------------------------------------

async def m_get_me(token: str, params: dict, request: Request):
    return {"ok": True, "result": {**bot_user(token), "can_join_groups": True,
                                   "can_read_all_group_messages": False,
                                   "supports_inline_queries": False}}


async def m_send_message(token: str, params: dict, request: Request):
    chat_id, text = params.get("chat_id"), params.get("text")
    if chat_id in (None, ""):
        return error(400, "Bad Request: chat_id is empty")
    if not text:
        return error(400, "Bad Request: message text is empty")
    reply_markup = params.get("reply_markup")
    if isinstance(reply_markup, str):
        try:
            reply_markup = json.loads(reply_markup)
        except json.JSONDecodeError:
            return error(400, "Bad Request: can't parse reply markup JSON object")
    stored = text if not reply_markup else json.dumps(
        {"text": text, "reply_markup": reply_markup}, ensure_ascii=False)
    await capture(token, request, chat_id, stored, {**params, "reply_markup": reply_markup})
    result = message_object(token, chat_id, text=text)
    if reply_markup:
        result["reply_markup"] = reply_markup
    return {"ok": True, "result": result}


async def m_send_photo(token: str, params: dict, request: Request):
    chat_id = params.get("chat_id")
    if chat_id in (None, ""):
        return error(400, "Bad Request: chat_id is empty")
    photo = params.get("photo") or ""
    caption = params.get("caption", "")
    await capture(token, request, chat_id, caption or str(photo)[:80], params)
    return {"ok": True, "result": message_object(
        token, chat_id, caption=caption,
        photo=[{"file_id": str(photo)[:64], "file_unique_id": str(photo)[:16],
                "width": 1280, "height": 720, "file_size": 1024}])}


async def m_send_document(token: str, params: dict, request: Request):
    chat_id = params.get("chat_id")
    if chat_id in (None, ""):
        return error(400, "Bad Request: chat_id is empty")
    document = params.get("document") or ""
    caption = params.get("caption", "")
    await capture(token, request, chat_id, caption or str(document)[:80], params)
    return {"ok": True, "result": message_object(
        token, chat_id, caption=caption,
        document={"file_id": str(document)[:64], "file_unique_id": str(document)[:16],
                  "file_name": str(document)[:64], "file_size": 2048})}


async def m_edit_message_text(token: str, params: dict, request: Request):
    chat_id, text = params.get("chat_id"), params.get("text")
    if not text:
        return error(400, "Bad Request: message text is empty")
    if not params.get("message_id"):
        return error(400, "Bad Request: message identifier is not specified")
    await capture(token, request, chat_id, text, params)
    result = message_object(token, chat_id, text=text, edit_date=int(time.time()))
    result["message_id"] = int(params["message_id"])
    return {"ok": True, "result": result}


async def m_delete_message(token: str, params: dict, request: Request):
    if not params.get("message_id"):
        return error(400, "Bad Request: message identifier is not specified")
    return {"ok": True, "result": True}


async def m_send_chat_action(token: str, params: dict, request: Request):
    if params.get("chat_id") in (None, ""):
        return error(400, "Bad Request: chat_id is empty")
    if not params.get("action"):
        return error(400, "Bad Request: action is empty")
    return {"ok": True, "result": True}


async def m_answer_callback_query(token: str, params: dict, request: Request):
    if not params.get("callback_query_id"):
        return error(400, "Bad Request: query id is empty")
    return {"ok": True, "result": True}


async def m_get_chat(token: str, params: dict, request: Request):
    chat_id = params.get("chat_id")
    if chat_id in (None, ""):
        return error(400, "Bad Request: chat_id is empty")
    return {"ok": True, "result": {**chat_of(chat_id), "first_name": "MockPost Chat"}}


async def m_get_updates(token: str, params: dict, request: Request):
    """Subset replica: returns the simulated inbound messages of that bot."""
    from mockpost.store import list_messages
    msgs = await list_messages(channel="telegram", test_id=get_test_id(request), limit=100)
    inbound = [m for m in msgs if m["direction"] == "inbound"
               and str(m["sender"] or "").startswith("chat:")]
    updates = [
        {"update_id": i + 1,
         "message": {"message_id": i + 1,
                     "chat": chat_of(str(m["sender"]).removeprefix("chat:")),
                     "text": m["body"], "date": int(time.time()),
                     "from": {"id": 0, "is_bot": False, "username": "simulated"}}}
        for i, m in enumerate(inbound)
    ]
    return {"ok": True, "result": updates}


async def m_set_webhook(token: str, params: dict, request: Request):
    url = params.get("url")
    if not url:
        return error(400, "Bad Request: url is required")
    app = await resolve_app("telegram", token)
    await register_webhook("telegram", url, token=token, config={"bot_token": token},
                           app_id=app["id"] if app else None)
    return {"ok": True, "result": True, "description": "Webhook was set"}


async def m_delete_webhook(token: str, params: dict, request: Request):
    db = get_db()
    await db.execute("DELETE FROM webhooks_registry WHERE channel='telegram' AND token=?", (token,))
    await db.commit()
    return {"ok": True, "result": True, "description": "Webhook was deleted"}


async def m_get_webhook_info(token: str, params: dict, request: Request):
    # Read from the registry, not from process memory: a restart must not
    # forget the webhook the app registered.
    db = get_db()
    cur = await db.execute(
        "SELECT target_url FROM webhooks_registry WHERE channel='telegram' AND token=? "
        "ORDER BY created_at DESC LIMIT 1", (token,))
    row = await cur.fetchone()
    return {"ok": True, "result": {"url": row["target_url"] if row else "",
                                   "has_custom_certificate": False,
                                   "pending_update_count": 0,
                                   "max_connections": 40}}


METHODS = {
    "getme": m_get_me,
    "sendmessage": m_send_message,
    "sendphoto": m_send_photo,
    "senddocument": m_send_document,
    "editmessagetext": m_edit_message_text,
    "deletemessage": m_delete_message,
    "sendchataction": m_send_chat_action,
    "answercallbackquery": m_answer_callback_query,
    "getchat": m_get_chat,
    "getupdates": m_get_updates,
    "setwebhook": m_set_webhook,
    "deletewebhook": m_delete_webhook,
    "getwebhookinfo": m_get_webhook_info,
}


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


@router.api_route("/bot{token}/{method}", methods=["GET", "POST"])
async def bot_api(token: str, method: str, request: Request):
    if not token or (settings.strict_auth and not TOKEN_RE.match(token)):
        return error(401, "Unauthorized")
    handler = METHODS.get(method.lower())
    if handler is None:
        return error(404, "Not Found: method not found")
    params = await read_params(request)
    return await handler(token, params, request)
