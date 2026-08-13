"""Incoming webhooks de Slack y Discord."""

from __future__ import annotations

from fastapi import APIRouter, Request

from mockpost.request_ctx import get_test_id
from mockpost.store import insert_message

router = APIRouter(tags=["team_webhooks"])


@router.post("/slack/webhook/{webhook_id}")
async def slack_webhook(webhook_id: str, request: Request):
    data = await request.json()
    text = data.get("text", "")
    msg_id = await insert_message(
        "slack", "outbound", text,
        sender=f"slack-webhook:{webhook_id}", recipient="channel",
        raw_payload=data, status="received", test_id=get_test_id(request),
    )
    return "ok"


@router.post("/discord/webhook/{webhook_id}")
async def discord_webhook(webhook_id: str, request: Request):
    data = await request.json()
    content = data.get("content", "")
    msg_id = await insert_message(
        "discord", "outbound", content,
        sender=f"discord-webhook:{webhook_id}", recipient="channel",
        raw_payload=data, status="received", test_id=get_test_id(request),
    )
    return {"id": msg_id}
