"""Native push: FCM HTTP v1 and APNs provider API.

Fidelity notes:

- **APNs** answers 200 with an EMPTY body and the `apns-id` header, never a
  JSON body; failures are `{"reason": "..."}` with the documented status
  (400 BadDeviceToken, 410 Unregistered, 413 PayloadTooLarge). A backend that
  prunes dead tokens keys off exactly that, so it needs to be reproducible:
  POST /apns/simulate/unregister marks a token as gone.
- **FCM** enforces the token/topic/condition exclusivity, answers Google's
  error envelope (code, message, status, details) and honours validate_only
  as a dry run. POST /fcm/simulate/unregister makes a token answer 404
  UNREGISTERED.
"""

from __future__ import annotations

import json
import re
import time
import uuid

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from mockpost.config import settings
from mockpost.request_ctx import get_test_id
from mockpost.store import get_device_state, insert_message, set_device_state

router = APIRouter(tags=["push_native"])

APNS_MAX_PAYLOAD = 4096
DEVICE_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def google_error(message: str, status: str, code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "status": status,
                                   "details": [{"@type": "type.googleapis.com/google.firebase.fcm."
                                                         "v1.FcmError", "errorCode": status}]}},
                        status_code=code)


@router.post("/fcm/simulate/unregister")
async def fcm_simulate_unregister(request: Request):
    """Make a token answer 404 UNREGISTERED, as FCM does for uninstalled apps."""
    data = await request.json()
    token = data.get("token", "")
    await set_device_state("fcm", token, "unregistered")
    return {"ok": True, "token": token, "state": "unregistered"}


@router.post("/fcm/v1/projects/{project_id}/messages:send")
async def fcm_send(project_id: str, request: Request):
    # FCM always requires the OAuth bearer, with or without strict mode: any
    # client that talks to it already sends one.
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        return google_error("Request is missing required authentication credential.",
                            "UNAUTHENTICATED", 401)

    data = await request.json()
    message = data.get("message") or {}
    targets = [key for key in ("token", "topic", "condition") if message.get(key)]
    if len(targets) != 1:
        return google_error(
            "Exactly one of token, topic or condition must be set in message.",
            "INVALID_ARGUMENT", 400)

    token = message.get("token", "")
    if token and await get_device_state("fcm", token) == "unregistered":
        return google_error("Requested entity was not found.", "UNREGISTERED", 404)

    notification = message.get("notification") or {}
    body = notification.get("body") or json.dumps(message.get("data") or {}, ensure_ascii=False)
    name = f"projects/{project_id}/messages/0:{int(time.time() * 1000)}%{uuid.uuid4().hex[:16]}"
    if data.get("validate_only"):
        # Dry run: FCM validates and returns the name without delivering.
        return {"name": name}

    await insert_message(
        "fcm", "outbound", body,
        sender=f"fcm:project:{project_id}", recipient=token or message.get("topic")
        or message.get("condition"),
        raw_payload=data, status="received", test_id=get_test_id(request),
        meta={"target": targets[0], "title": notification.get("title"),
              "android": message.get("android"), "apns": message.get("apns"),
              "webpush": message.get("webpush")},
    )
    return {"name": name}


@router.post("/apns/simulate/unregister")
async def apns_simulate_unregister(request: Request):
    """Make a device token answer 410 Unregistered on the next push."""
    data = await request.json()
    token = data.get("device_token", "")
    await set_device_state("apns", token, "unregistered")
    return {"ok": True, "device_token": token, "state": "unregistered"}


@router.post("/apns/3/device/{device_token}")
async def apns_send(device_token: str, request: Request):
    apns_id = request.headers.get("apns-id") or str(uuid.uuid4())
    headers = {"apns-id": apns_id}

    if settings.strict_auth:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return JSONResponse({"reason": "MissingProviderToken"}, status_code=401, headers=headers)
        if not request.headers.get("apns-topic"):
            return JSONResponse({"reason": "MissingTopic"}, status_code=400, headers=headers)
        if not DEVICE_TOKEN_RE.match(device_token):
            return JSONResponse({"reason": "BadDeviceToken"}, status_code=400, headers=headers)

    if await get_device_state("apns", device_token) == "unregistered":
        return JSONResponse({"reason": "Unregistered", "timestamp": int(time.time() * 1000)},
                            status_code=410, headers=headers)

    raw = await request.body()
    if len(raw) > APNS_MAX_PAYLOAD:
        return JSONResponse({"reason": "PayloadTooLarge"}, status_code=413, headers=headers)
    try:
        data = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return JSONResponse({"reason": "BadMessageId"}, status_code=400, headers=headers)

    aps = data.get("aps") or {} if isinstance(data, dict) else {}
    alert = aps.get("alert", "")
    body = alert if isinstance(alert, str) else (alert.get("body") or alert.get("title") or "")
    await insert_message(
        "apns", "outbound", str(body),
        sender="apns", recipient=device_token,
        raw_payload=data, status="received", test_id=get_test_id(request),
        meta={"apns_id": apns_id, "topic": request.headers.get("apns-topic"),
              "push_type": request.headers.get("apns-push-type"),
              "priority": request.headers.get("apns-priority"),
              "expiration": request.headers.get("apns-expiration"),
              "collapse_id": request.headers.get("apns-collapse-id"),
              "payload_bytes": len(raw)},
    )
    # Real APNs: 200 with no body, the id travels in the apns-id header.
    return Response(status_code=200, headers=headers)
