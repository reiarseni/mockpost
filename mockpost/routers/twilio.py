"""SMS via the Twilio API (subset): Messages.json + StatusCallback."""

from __future__ import annotations

from fastapi import APIRouter, Request

from mockpost.apps import resolve_app
from mockpost.request_ctx import get_test_id
from mockpost.store import insert_message
from mockpost.webhooks import deliver_to_app_webhooks

router = APIRouter(prefix="/twilio", tags=["twilio"])


@router.post("/2010-04-01/Accounts/{sid}/Messages.json")
async def send_message(sid: str, request: Request):
    form = await request.form()
    to = form.get("To", "")
    body = form.get("Body", "")
    test_id = get_test_id(request)
    app = await resolve_app("twilio", sid)
    app_id = app["id"] if app else None
    msg_id = await insert_message(
        "sms", "outbound", body,
        sender=f"twilio:{sid}", recipient=to,
        raw_payload=dict(form), status="received", test_id=test_id, app_id=app_id,
    )
    # Replica of the Twilio response
    response = {
        "sid": msg_id, "account_sid": sid, "to": to, "from": form.get("From"),
        "body": body, "status": "queued", "direction": "outbound-api",
        "price": None, "error_code": None, "uri": f"/2010-04-01/Accounts/{sid}/Messages/{msg_id}.json",
    }
    # Simulated StatusCallback: only to the same app's webhooks
    if form.get("StatusCallback"):
        await deliver_to_app_webhooks(
            "sms", "status_update",
            {"MessageSid": msg_id, "MessageStatus": "delivered", "To": to},
            test_id=test_id, app_id=app_id,
        )
    return response


@router.post("/2010-04-01/Accounts/{sid}/Messages/{mid}.json")
async def get_message(sid: str, mid: str):
    return {"sid": mid, "account_sid": sid, "status": "delivered", "direction": "outbound-api"}
