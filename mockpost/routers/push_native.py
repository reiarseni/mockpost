"""Native push: FCM and APNs (payload shape, without real signature validation)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mockpost.request_ctx import get_test_id
from mockpost.store import insert_message

router = APIRouter(tags=["push_native"])


@router.post("/fcm/v1/projects/{project_id}/messages:send")
async def fcm_send(project_id: str, request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": {"code": 401, "message": "Missing bearer token"}}, status_code=401)
    data = await request.json()
    token = (data.get("message") or {}).get("token", "")
    notification = ((data.get("message") or {}).get("notification") or {}).get("body", "")
    msg_id = await insert_message(
        "fcm", "outbound", notification or "",
        sender=f"fcm:project:{project_id}", recipient=token,
        raw_payload=data, status="received", test_id=get_test_id(request),
    )
    return {"name": f"projects/{project_id}/messages/{msg_id}"}


@router.post("/apns/3/device/{device_token}")
async def apns_send(device_token: str, request: Request):
    data = await request.json()
    body = (data.get("aps") or {}).get("alert", "") if isinstance(data, dict) else ""
    msg_id = await insert_message(
        "apns", "outbound", str(body),
        sender="apns", recipient=device_token,
        raw_payload=data, status="received", test_id=get_test_id(request),
    )
    return JSONResponse({"apns-id": msg_id}, status_code=200)
