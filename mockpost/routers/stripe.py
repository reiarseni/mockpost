"""Stripe: outbound endpoints (real shape) + signed events back to the app."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Request

from mockpost.apps import resolve_app
from mockpost.config import utcnow
from mockpost.db import get_db
from mockpost.request_ctx import get_app_id, get_test_id
from mockpost.signing import stripe_signature
from mockpost.store import insert_message
from mockpost.webhooks import deliver_webhook

router = APIRouter(prefix="/stripe", tags=["stripe"])


def _stripe_obj(obj: str, **extra) -> dict:
    return {"id": f"{obj[:2]}_{uuid.uuid4().hex[:16]}", "object": obj, "livemode": False, **extra}


def _stripe_key(request: Request) -> str | None:
    """Fake Stripe API key (Authorization header, part of the real protocol)."""
    auth = request.headers.get("Authorization", "")
    return auth.removeprefix("Bearer ").strip() or None


@router.post("/v1/checkout/sessions")
async def create_checkout_session(request: Request):
    form = await request.form()
    session = _stripe_obj("cs", mode="payment", status="open",
                          success_url=form.get("success_url"), cancel_url=form.get("cancel_url"),
                          amount_total=int(form.get("amount_total") or 0),
                          currency=form.get("currency", "usd"))
    app = await resolve_app("stripe", _stripe_key(request))
    msg_id = await insert_message(
        "stripe", "outbound", f"checkout session {session['id']} created",
        sender="stripe", recipient=form.get("success_url"),
        raw_payload=session, status="received", test_id=get_test_id(request),
        app_id=app["id"] if app else None,
    )
    return session


@router.post("/v1/payment_intents")
async def create_payment_intent(request: Request):
    form = await request.form()
    pi = _stripe_obj("pi", amount=int(form.get("amount") or 0), currency=form.get("currency", "usd"),
                     status="requires_confirmation")
    app = await resolve_app("stripe", _stripe_key(request))
    msg_id = await insert_message(
        "stripe", "outbound", f"payment intent {pi['id']} created",
        sender="stripe", recipient=None,
        raw_payload=pi, status="received", test_id=get_test_id(request),
    )
    return pi


@router.post("/simulate_event")
async def simulate_event(request: Request):
    """Build and send a simulated signed Stripe event to the webhook
    of the given app (X-MockPost-App), or by the API key if present in the header."""
    data = await request.json()
    event_type = data.get("event_type", "checkout.session.completed")
    overrides = data.get("overrides", {})
    test_id = get_test_id(request)
    app_id = await get_app_id(request)
    if not app_id:
        app = await resolve_app("stripe", _stripe_key(request))
        app_id = app["id"] if app else None

    payload = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "object": "event",
        "type": event_type,
        "data": {"object": _stripe_obj("cs", status="complete", payment_status="paid")},
        "created": int(__import__("time").time()),
        "livemode": False,
    }
    if overrides:
        payload["data"]["object"].update(overrides)

    db = get_db()
    wh = None
    if app_id:
        cur = await db.execute(
            "SELECT * FROM webhooks_registry WHERE channel='stripe' AND app_id=? ORDER BY created_at DESC LIMIT 1",
            (app_id,))
        wh = await cur.fetchone()
    body = json.dumps(payload, ensure_ascii=False)
    signature = stripe_signature(body)

    result = None
    if wh:
        result = await deliver_webhook("stripe", wh["target_url"], event_type, payload,
                                       headers={"Stripe-Signature": signature},
                                       test_id=test_id, app_id=app_id)
    await db.execute(
        "INSERT INTO stripe_events (id, test_id, event_type, payload, webhook_url, signature, sent_at, response_code, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (payload["id"], test_id, event_type, body, wh["target_url"] if wh else None,
         signature, utcnow(), result["response_code"] if result else None, utcnow()),
    )
    await db.commit()
    return {"ok": True, "event": payload, "signature": signature, "app_id": app_id, "delivered": result}


@router.post("/webhook")
async def webhook_receiver(request: Request):
    """Endpoint for the app to receive/validate events — registered via panel/API."""
    return {"received": True}
