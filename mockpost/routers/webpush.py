"""Web Push: a real push service (RFC 8030/8188/8291/8292) plus /webpush/send.

Two different roles, both useful:

- **Push service** — `/webpush/subscribe` hands out a browser-shaped
  PushSubscription whose `endpoint` lives here, and the backend then POSTs to
  that endpoint exactly what pywebpush, web-push (node) or WebPushSharp send:
  an `aes128gcm` encrypted body plus an `Authorization: vapid` header. MockPost
  verifies the VAPID signature, decrypts the payload with the subscription key
  it generated, answers `201 Created` and captures the cleartext. This is what a
  backend talks to in production (FCM, Mozilla autopush), so nothing in the app
  changes.
- **Sender shortcut** — `/webpush/send` takes a plain JSON envelope for callers
  that only want to record a notification without doing the crypto. It stays
  supported for backwards compatibility.
"""

from __future__ import annotations

import base64
import json
import os
import uuid

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mockpost.config import settings, utcnow
from mockpost.db import get_db
from mockpost.request_ctx import get_app_id, get_test_id
from mockpost.signing import verify_vapid, vapid_public_key_b64
from mockpost.store import insert_message

router = APIRouter(prefix="/webpush", tags=["webpush"])

SUPPORTED_ENCODINGS = ("aes128gcm", "aesgcm")


class Subscription(BaseModel):
    endpoint: str
    keys: dict  # {p256dh, auth}


class SubscribeRequest(BaseModel):
    """Everything is optional: with no body MockPost generates the key pair."""
    endpoint: str | None = None
    keys: dict | None = None


class PushPayload(BaseModel):
    subscription: Subscription
    payload: str | None = None
    ttl: int = 60
    topic: str | None = None


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def generate_subscription_keys() -> dict:
    """A browser's subscription key pair: P-256 for p256dh, 16 bytes for auth."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    p256dh = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    private_raw = private_key.private_numbers().private_value.to_bytes(32, "big")
    return {"p256dh": b64url(p256dh), "auth": b64url(os.urandom(16)),
            "private_key": b64url(private_raw)}


def decrypt_payload(body: bytes, private_raw: str, auth: str, encoding: str) -> tuple[str | None, str]:
    """Decrypt an RFC 8291 payload. Returns (cleartext, note)."""
    if not body:
        return "", "empty payload"
    if not private_raw:
        return None, "subscription keys were supplied by the client, no private key to decrypt"
    if encoding != "aes128gcm":
        return None, f"content-encoding {encoding} is not decrypted"
    try:
        import http_ece
        from cryptography.hazmat.primitives.asymmetric import ec

        private_key = ec.derive_private_key(
            int.from_bytes(b64url_decode(private_raw), "big"), ec.SECP256R1())
        clear = http_ece.decrypt(body, private_key=private_key,
                                 auth_secret=b64url_decode(auth), version="aes128gcm")
        return clear.decode("utf-8", errors="replace"), "decrypted"
    except Exception as exc:
        return None, f"decryption failed: {type(exc).__name__}: {exc}"


async def get_subscription(sub_id: str) -> dict | None:
    db = get_db()
    cur = await db.execute("SELECT * FROM webpush_subscriptions WHERE id=?", (sub_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


@router.post("/subscribe")
async def subscribe(request: Request, body: SubscribeRequest | None = None):
    """Hand out a PushSubscription shaped like the browser's PushManager.

    With no body (or with only `endpoint`), MockPost generates the key pair and
    keeps the private half, so it can decrypt what the backend sends. If the
    caller supplies its own `keys`, they are stored as-is and payloads are kept
    encrypted."""
    db = get_db()
    sub_id = str(uuid.uuid4())
    supplied = (body.keys if body else None) or {}
    if supplied.get("p256dh") and supplied.get("auth"):
        keys = {"p256dh": supplied["p256dh"], "auth": supplied["auth"], "private_key": ""}
    else:
        keys = generate_subscription_keys()

    base = f"{request.base_url.scheme}://{request.base_url.netloc}"
    endpoint = (body.endpoint if body else None) or f"{base}/webpush/push/{sub_id}"
    await db.execute(
        "INSERT INTO webpush_subscriptions (id, endpoint, p256dh, auth, private_key, "
        "vapid_public_key, status, test_id, app_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
        (sub_id, endpoint, keys["p256dh"], keys["auth"], keys["private_key"],
         vapid_public_key_b64(), get_test_id(request), await get_app_id(request), utcnow()),
    )
    await db.commit()
    return {
        # Browser PushSubscription shape (JSON.stringify(subscription))
        "endpoint": endpoint,
        "expirationTime": None,
        "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
        # MockPost extras
        "id": sub_id,
        "vapid_public_key": vapid_public_key_b64(),
    }


@router.get("/subscriptions")
async def list_subscriptions():
    db = get_db()
    cur = await db.execute("SELECT id, endpoint, p256dh, auth, status, created_at "
                           "FROM webpush_subscriptions ORDER BY created_at DESC")
    return [dict(r) for r in await cur.fetchall()]


@router.post("/subscriptions/{sub_id}/expire")
async def expire_subscription(sub_id: str):
    """Mark a subscription as gone: the next push answers 410, like a real
    push service does when the browser unsubscribes."""
    if not await get_subscription(sub_id):
        return JSONResponse({"error": "not_found", "id": sub_id}, status_code=404)
    db = get_db()
    await db.execute("UPDATE webpush_subscriptions SET status='gone' WHERE id=?", (sub_id,))
    await db.commit()
    return {"id": sub_id, "status": "gone"}


@router.post("/push/{sub_id}")
async def push(sub_id: str, request: Request):
    """Receive the encrypted push, as FCM or Mozilla autopush would."""
    subscription = await get_subscription(sub_id)
    if not subscription:
        return JSONResponse({"error": "not_found", "id": sub_id}, status_code=404)
    if subscription["status"] == "gone":
        # RFC 8030: the subscription no longer exists; the app must delete it.
        return Response(status_code=410)

    audience = f"{request.base_url.scheme}://{request.base_url.netloc}"
    authorization = request.headers.get("Authorization", "")
    if not verify_vapid(authorization, audience):
        return JSONResponse({"error": "unauthorized", "reason": "invalid VAPID signature"},
                            status_code=401)

    encoding = (request.headers.get("Content-Encoding") or "").strip()
    body = await request.body()
    if body and encoding not in SUPPORTED_ENCODINGS:
        return JSONResponse(
            {"error": "unsupported_media_type",
             "reason": f"Content-Encoding must be one of {', '.join(SUPPORTED_ENCODINGS)}"},
            status_code=415)
    ttl_header = request.headers.get("TTL")
    if ttl_header is None and settings.strict_auth:
        # RFC 8030 section 5.2 makes TTL mandatory; only enforced under strict.
        return JSONResponse({"error": "bad_request", "reason": "missing TTL header"},
                            status_code=400)

    cleartext, note = decrypt_payload(body, subscription["private_key"] or "",
                                      subscription["auth"], encoding)
    msg_id = await insert_message(
        "webpush", "outbound", cleartext if cleartext is not None else "",
        sender=audience, recipient=subscription["endpoint"],
        raw_payload=cleartext if cleartext is not None else b64url(body),
        status="received", test_id=get_test_id(request), app_id=subscription["app_id"],
        meta={"subscription_id": sub_id, "content_encoding": encoding or None,
              "ttl": ttl_header, "topic": request.headers.get("Topic"),
              "urgency": request.headers.get("Urgency"),
              "encrypted_bytes": len(body), "decryption": note,
              "vapid": authorization[:64]},
    )
    headers = {"Location": f"{audience}/webpush/receipt/{msg_id}"}
    if ttl_header is not None:
        headers["TTL"] = ttl_header
    return Response(status_code=201, headers=headers)


@router.post("/send")
async def send(payload: PushPayload, request: Request):
    """Sender shortcut: JSON envelope, no crypto. Kept for compatibility."""
    auth = request.headers.get("Authorization", "")
    audience = f"{request.base_url.scheme}://{request.base_url.netloc}"
    if not verify_vapid(auth, audience):
        return JSONResponse({"ok": False, "error": "Unauthorized: invalid VAPID signature"},
                            status_code=401)
    msg_id = await insert_message(
        "webpush", "outbound", payload.payload or "",
        sender=audience, recipient=payload.subscription.endpoint,
        raw_payload=json.dumps(payload.model_dump(), ensure_ascii=False), status="received",
        test_id=get_test_id(request),
    )
    return {"ok": True, "message_id": msg_id, "accepted": True}
