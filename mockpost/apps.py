"""App registry: per-channel credentials -> app identity.

Each user app is identified by the FAKE credentials it uses to talk to
MockPost (Telegram bot token, Twilio SID, Stripe sk_test_, WhatsApp
phone_id, FCM project_id, SMTP port). The app sends no extra headers:
MockPost derives the app from what already travels in the real protocol.
"""

from __future__ import annotations

import json
import uuid

from mockpost.config import utcnow
from mockpost.db import get_db


async def list_apps() -> list[dict]:
    db = get_db()
    cur = await db.execute("SELECT * FROM apps ORDER BY created_at ASC")
    out = []
    for r in await cur.fetchall():
        d = dict(r)
        d["creds"] = json.loads(d["creds"])
        out.append(d)
    return out


async def get_app(app_id: str) -> dict | None:
    db = get_db()
    cur = await db.execute("SELECT * FROM apps WHERE id=?", (app_id,))
    r = await cur.fetchone()
    if not r:
        return None
    d = dict(r)
    d["creds"] = json.loads(d["creds"])
    return d


async def get_app_by_name(name: str) -> dict | None:
    db = get_db()
    cur = await db.execute("SELECT * FROM apps WHERE name=?", (name,))
    r = await cur.fetchone()
    if not r:
        return None
    d = dict(r)
    d["creds"] = json.loads(d["creds"])
    return d


async def upsert_app(name: str, creds: dict | None = None) -> dict:
    """Create the app, or update its credentials if it already exists (same name)."""
    db = get_db()
    existing = await get_app_by_name(name)
    creds = creds or {}
    if existing:
        merged = {**existing["creds"], **creds}
        await db.execute("UPDATE apps SET creds=? WHERE id=?", (json.dumps(merged), existing["id"]))
        await db.commit()
        return await get_app(existing["id"])  # type: ignore[return-value]
    app_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO apps (id, name, creds, created_at) VALUES (?, ?, ?, ?)",
        (app_id, name, json.dumps(creds, ensure_ascii=False), utcnow()),
    )
    await db.commit()
    return {"id": app_id, "name": name, "creds": creds, "created_at": utcnow()}


async def delete_app(app_id: str) -> None:
    db = get_db()
    await db.execute("DELETE FROM apps WHERE id=?", (app_id,))
    # the app's webhooks become global (app_id NULL)
    await db.execute("UPDATE webhooks_registry SET app_id=NULL WHERE app_id=?", (app_id,))
    await db.commit()


async def resolve_app(channel: str, credential: str | None) -> dict | None:
    """Resolve the app from a channel + the fake credential the request carries.

    channel: telegram|twilio|stripe|whatsapp|fcm|apns|slack|discord|webpush|smtp
    credential: bot token, SID, sk_test_, phone_id, project_id, SMTP port...
    """
    if not credential:
        return None
    apps = await list_apps()
    key = {
        "telegram": "telegram_token", "twilio": "twilio_sid", "stripe": "stripe_key",
        "whatsapp": "whatsapp_phone_id", "fcm": "fcm_project_id", "apns": "apns_key",
        "slack": "slack_webhook_id", "discord": "discord_webhook_id",
        "webpush": "vapid_contact", "smtp": "smtp_port",
    }.get(channel)
    if not key:
        return None
    for app in apps:
        if app["creds"].get(key) == credential:
            return app
    return None
