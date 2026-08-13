"""Incoming webhooks for Slack and Discord.

Fidelity notes:

- **Slack** answers the literal string `ok` as text/plain on success and
  `invalid_payload` with 400 when neither text nor blocks are present, which
  is what its incoming-webhook endpoint does.
- **Discord** answers **204 with no body**, unless the caller asks for
  `?wait=true` and only then returns the message object. Clients that check
  `response.status == 204` were getting a 200 with JSON here.
- Both accept the payload as JSON or as a form field (`payload` /
  `payload_json`), the two shapes their docs describe.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from mockpost.request_ctx import get_test_id
from mockpost.store import insert_message

router = APIRouter(tags=["team_webhooks"])


async def read_payload(request: Request) -> dict:
    """JSON body, or the `payload` / `payload_json` form field."""
    content_type = (request.headers.get("Content-Type") or "").split(";")[0].strip()
    if content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
        form = await request.form()
        raw = form.get("payload") or form.get("payload_json") or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def blocks_summary(blocks: list | None) -> str:
    """Readable line out of Slack blocks, so the timeline is never empty."""
    texts = []
    for block in blocks or []:
        text = block.get("text")
        if isinstance(text, dict):
            texts.append(text.get("text", ""))
        elif isinstance(text, str):
            texts.append(text)
        for field in block.get("fields") or []:
            if isinstance(field, dict):
                texts.append(field.get("text", ""))
    return " | ".join(t for t in texts if t)


def embeds_summary(embeds: list | None) -> str:
    parts = []
    for embed in embeds or []:
        parts.append(" ".join(str(embed.get(k, "")) for k in ("title", "description")
                              if embed.get(k)))
    return " | ".join(p for p in parts if p)


@router.post("/slack/webhook/{webhook_id}")
async def slack_webhook(webhook_id: str, request: Request):
    data = await read_payload(request)
    text = data.get("text") or blocks_summary(data.get("blocks"))
    if not text:
        # Real Slack: 400 with the plain string invalid_payload.
        return PlainTextResponse("invalid_payload", status_code=400)
    await insert_message(
        "slack", "outbound", text,
        sender=f"slack-webhook:{webhook_id}", recipient=data.get("channel", "channel"),
        raw_payload=data, status="received", test_id=get_test_id(request),
        meta={"blocks": data.get("blocks"), "username": data.get("username"),
              "icon_emoji": data.get("icon_emoji"), "thread_ts": data.get("thread_ts")},
    )
    return PlainTextResponse("ok")


@router.post("/discord/webhook/{webhook_id}")
async def discord_webhook(webhook_id: str, request: Request):
    data = await read_payload(request)
    content = data.get("content") or embeds_summary(data.get("embeds"))
    if not content:
        return JSONResponse({"message": "Cannot send an empty message", "code": 50006},
                            status_code=400)
    msg_id = await insert_message(
        "discord", "outbound", content,
        sender=f"discord-webhook:{webhook_id}", recipient="channel",
        raw_payload=data, status="received", test_id=get_test_id(request),
        meta={"embeds": data.get("embeds"), "username": data.get("username"),
              "tts": data.get("tts", False)},
    )
    if request.query_params.get("wait", "").lower() == "true":
        return {"id": str(uuid.uuid4().int)[:18], "type": 0, "content": content,
                "channel_id": webhook_id, "webhook_id": webhook_id,
                "embeds": data.get("embeds") or [], "mockpost_message_id": msg_id}
    # Real Discord: 204 No Content unless ?wait=true.
    return Response(status_code=204)
