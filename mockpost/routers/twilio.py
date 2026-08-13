"""SMS via the Twilio API (subset): Messages.json + StatusCallback.

Fidelity notes, mirroring api.twilio.com:

- Authentication is HTTP Basic (AccountSid + AuthToken). Under strict auth a
  missing header answers the real 401 body {"code": 20003, ...}.
- Message SIDs are `SM` + 32 hex characters, which is what clients assert on.
- The response carries the fields the SDKs read: status, direction, dates,
  num_segments, api_version, uri and subresource_uris.
- StatusCallback is posted as x-www-form-urlencoded to the URL the client
  passed, exactly like Twilio does; the same event still reaches the app's
  registered webhooks.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mockpost.apps import resolve_app
from mockpost.config import settings, utcnow
from mockpost.request_ctx import get_test_id
from mockpost.store import insert_message
from mockpost.webhooks import deliver_to_app_webhooks, deliver_webhook

router = APIRouter(prefix="/twilio", tags=["twilio"])

API_VERSION = "2010-04-01"


def message_sid() -> str:
    return "SM" + uuid.uuid4().hex


def twilio_error(message: str, code: int, status: int) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, "status": status,
                         "more_info": f"https://www.twilio.com/docs/errors/{code}"},
                        status_code=status)


def _unauthenticated(request: Request) -> bool:
    return settings.strict_auth and not request.headers.get("Authorization", "").startswith("Basic ")


@router.post(f"/{API_VERSION}/Accounts/{{sid}}/Messages.json")
async def send_message(sid: str, request: Request):
    if _unauthenticated(request):
        return twilio_error("Authenticate", 20003, 401)

    form = await request.form()
    to = form.get("To", "")
    body = form.get("Body", "")
    if not to:
        return twilio_error("The 'To' number is required", 21604, 400)

    test_id = get_test_id(request)
    app = await resolve_app("twilio", sid)
    app_id = app["id"] if app else None
    msg_sid = message_sid()
    now = utcnow()
    await insert_message(
        "sms", "outbound", body,
        sender=form.get("From") or f"twilio:{sid}", recipient=to,
        raw_payload=dict(form), status="received", test_id=test_id, app_id=app_id,
        meta={"sid": msg_sid, "messaging_service_sid": form.get("MessagingServiceSid"),
              "status_callback": form.get("StatusCallback")},
    )
    response = {
        "sid": msg_sid, "account_sid": sid, "to": to, "from": form.get("From"),
        "body": body, "status": "queued", "direction": "outbound-api",
        "date_created": now, "date_updated": now, "date_sent": None,
        "num_segments": "1", "num_media": "0", "price": None, "price_unit": "USD",
        "error_code": None, "error_message": None, "api_version": API_VERSION,
        "messaging_service_sid": form.get("MessagingServiceSid"),
        "uri": f"/{API_VERSION}/Accounts/{sid}/Messages/{msg_sid}.json",
        "subresource_uris": {"media": f"/{API_VERSION}/Accounts/{sid}/Messages/{msg_sid}/Media.json"},
    }

    payload = {"MessageSid": msg_sid, "MessageStatus": "delivered", "To": to,
               "From": form.get("From") or "", "AccountSid": sid, "ApiVersion": API_VERSION}
    callback_url = form.get("StatusCallback")
    if callback_url:
        await deliver_webhook("sms", callback_url, "status_update", payload,
                              test_id=test_id, app_id=app_id, form=True)
    await deliver_to_app_webhooks("sms", "status_update", payload,
                                  test_id=test_id, app_id=app_id)
    return response


@router.api_route(f"/{API_VERSION}/Accounts/{{sid}}/Messages/{{mid}}.json",
                  methods=["GET", "POST"])
async def get_message(sid: str, mid: str, request: Request):
    if _unauthenticated(request):
        return twilio_error("Authenticate", 20003, 401)
    return {"sid": mid, "account_sid": sid, "status": "delivered",
            "direction": "outbound-api", "api_version": API_VERSION,
            "date_sent": utcnow(),
            "uri": f"/{API_VERSION}/Accounts/{sid}/Messages/{mid}.json"}
