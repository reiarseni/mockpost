"""Shared persistence for messages and events, used by routers and the API."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from mockpost.config import utcnow
from mockpost.db import get_db

CHANNELS = ("mail", "telegram", "whatsapp", "webpush", "sms", "fcm", "apns", "slack", "discord", "stripe")
STATUSES = ("received", "delivered", "read", "failed")

# 4-8 digit OTP pattern in the message body
OTP_RE = re.compile(r"\b(\d{4,8})\b")


async def insert_message(
    channel: str,
    direction: str,
    body: str = "",
    *,
    sender: str | None = None,
    recipient: str | None = None,
    subject: str | None = None,
    raw_payload: Any = None,
    status: str = "received",
    test_id: str | None = None,
    app_id: str | None = None,
    meta: dict | None = None,
) -> str:
    db = get_db()
    msg_id = str(uuid.uuid4())
    raw = raw_payload if isinstance(raw_payload, str) else json.dumps(raw_payload, ensure_ascii=False)
    await db.execute(
        "INSERT INTO messages (id, test_id, app_id, channel, direction, sender, recipient, subject, body, "
        "raw_payload, status, created_at, meta) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, test_id, app_id, channel, direction, sender, recipient, subject, body, raw, status, utcnow(),
         json.dumps(meta, ensure_ascii=False) if meta else None),
    )
    await db.commit()
    await maybe_store_otp(channel, body, recipient or sender, test_id, app_id)
    return msg_id


async def maybe_store_otp(channel: str, body: str, identifier: str | None, test_id: str | None,
                          app_id: str | None = None) -> None:
    """Detect a 4-8 digit OTP code in the body and store it in otp_codes.

    A mail can carry several recipients (comma-separated): one row per
    identifier, so get_latest_otp works for any of them."""
    if channel not in ("sms", "mail") or not identifier:
        return
    m = OTP_RE.search(body or "")
    if not m:
        return
    db = get_db()
    for single in [i.strip() for i in identifier.split(",") if i.strip()]:
        await db.execute(
            "INSERT INTO otp_codes (id, test_id, channel, identifier, code, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), test_id, channel, single, m.group(1), utcnow()),
        )
    await db.commit()


async def update_message_status(msg_id: str, status: str) -> None:
    db = get_db()
    now = utcnow()
    col = "delivered_at" if status == "delivered" else "read_at" if status == "read" else None
    if col:
        await db.execute(f"UPDATE messages SET status=?, {col}=? WHERE id=?", (status, now, msg_id))
    else:
        await db.execute("UPDATE messages SET status=? WHERE id=?", (status, msg_id))
    await db.commit()


async def get_message(msg_id: str) -> dict | None:
    db = get_db()
    cur = await db.execute("SELECT * FROM messages WHERE id=?", (msg_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def list_messages(*, channel: str | None = None, test_id: str | None = None,
                        status: str | None = None, limit: int = 20,
                        app_id: str | None = None) -> list[dict]:
    db = get_db()
    where, params = [], []
    if channel:
        where.append("channel=?")
        params.append(channel)
    if test_id:
        where.append("test_id=?")
        params.append(test_id)
    if status:
        where.append("status=?")
        params.append(status)
    if app_id:
        where.append("app_id=?")
        params.append(app_id)
    q = "SELECT * FROM messages"
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def clear_channel(channel: str | None, test_id: str | None = None,
                        app_id: str | None = None) -> int:
    db = get_db()
    where, params = [], []
    if channel:
        where.append("channel=?")
        params.append(channel)
    if test_id:
        where.append("test_id=?")
        params.append(test_id)
    if app_id:
        where.append("app_id=?")
        params.append(app_id)
    q = "DELETE FROM messages"
    if where:
        q += " WHERE " + " AND ".join(where)
    cur = await db.execute(q, params)
    await db.commit()
    return cur.rowcount


# Channels with webhooks back to the app (inbound/status/events). The rest only capture sends.
WEBHOOK_CHANNELS = ("telegram", "whatsapp", "sms", "stripe", "github", "facebook", "x")


async def register_webhook(channel: str, target_url: str, *, token: str | None = None,
                           config: dict | None = None, app_id: str | None = None) -> str:
    if channel not in WEBHOOK_CHANNELS:
        raise ValueError(f"channel '{channel}' does not support webhooks back to the app; "
                         f"valid: {', '.join(WEBHOOK_CHANNELS)}")
    db = get_db()
    wid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO webhooks_registry (id, app_id, channel, target_url, token, config, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (wid, app_id, channel, target_url, token, json.dumps(config or {}), utcnow()),
    )
    await db.commit()
    return wid


async def list_webhooks(channel: str | None = None, app_id: str | None = None) -> list[dict]:
    db = get_db()
    q = "SELECT * FROM webhooks_registry"
    where: list[str] = []
    params: list[Any] = []
    if channel:
        where.append("channel=?")
        params.append(channel)
    if app_id:
        where.append("app_id=?")
        params.append(app_id)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY created_at DESC"
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]


async def get_webhook(wid: str) -> dict | None:
    db = get_db()
    cur = await db.execute("SELECT * FROM webhooks_registry WHERE id=?", (wid,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def delete_webhook(wid: str) -> None:
    db = get_db()
    await db.execute("DELETE FROM webhooks_registry WHERE id=?", (wid,))
    await db.commit()
