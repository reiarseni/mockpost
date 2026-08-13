"""Human-readable web panel: timeline, channels, detail, configuration, webhooks, apps."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mockpost.apps import list_apps
from mockpost.request_ctx import get_test_id
from mockpost.store import get_message, list_messages, list_webhooks
from mockpost.timeline_builder import CHANNEL_ICONS, build_timeline, timeline_markdown

router = APIRouter(tags=["panel"])

TEMPLATES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates"))
templates = Jinja2Templates(directory=TEMPLATES_DIR)

CHANNEL_NAMES = {
    "mail": "Email", "telegram": "Telegram", "whatsapp": "WhatsApp", "webpush": "Web Push",
    "sms": "SMS", "fcm": "FCM", "apns": "APNs", "slack": "Slack", "discord": "Discord",
    "stripe": "Stripe", "github": "GitHub", "facebook": "Facebook", "x": "X",
}

# Channels that can receive webhooks back to the app (inbound/status/events).
# mail/webpush/fcm/apns/slack/discord only capture outbound sends from the app.
WEBHOOK_CHANNELS = ("telegram", "whatsapp", "sms", "stripe", "github", "facebook", "x")


@router.get("/", response_class=HTMLResponse)
async def timeline_page(request: Request, channel: str | None = None, q: str | None = None,
                        test_id: str | None = None, app: str | None = None):
    from mockpost.apps import get_app_by_name
    channels = [channel] if channel else None
    app_obj = await get_app_by_name(app) if app else None
    events = await build_timeline(channels=channels, test_id=test_id, limit=500,
                                  app_id=app_obj["id"] if app_obj else None)
    if q:
        events = [e for e in events if q.lower() in (e.summary + (e.sender or "") + (e.recipient or "")).lower()]
    md = timeline_markdown(events)
    apps = await list_apps()
    return templates.TemplateResponse(request, "timeline.html", {
        "events": events, "icons": CHANNEL_ICONS,
        "names": CHANNEL_NAMES, "channels": list(CHANNEL_NAMES), "current_channel": channel,
        "q": q or "", "test_id": test_id or "", "markdown": md,
        "apps": apps, "current_app": app or "",
    })


@router.get("/timeline", response_class=HTMLResponse)
async def timeline_redirect():
    return RedirectResponse("/")


@router.get("/timeline/markdown", response_class=PlainTextResponse)
async def timeline_md(request: Request, test_id: str | None = None, app: str | None = None):
    from mockpost.apps import get_app_by_name
    test_id = test_id or get_test_id(request)
    app_obj = await get_app_by_name(app) if app else None
    events = await build_timeline(test_id=test_id, limit=500,
                                  app_id=app_obj["id"] if app_obj else None)
    return timeline_markdown(events)


@router.get("/channel/{channel}", response_class=HTMLResponse)
async def channel_page(request: Request, channel: str, test_id: str | None = None, app: str | None = None):
    from mockpost.apps import get_app_by_name
    app_obj = await get_app_by_name(app) if app else None
    msgs = await list_messages(channel=channel, test_id=test_id, limit=200,
                               app_id=app_obj["id"] if app_obj else None)
    return templates.TemplateResponse(request, "channel.html", {
        "channel": channel, "messages": msgs,
        "name": CHANNEL_NAMES.get(channel, channel), "icon": CHANNEL_ICONS.get(channel, "📨"),
        "test_id": test_id or "",
    })


@router.get("/message/{message_id}", response_class=HTMLResponse)
async def message_page(request: Request, message_id: str):
    msg = await get_message(message_id)
    if msg is None:
        return HTMLResponse("<h1>Message not found</h1>", status_code=404)
    return templates.TemplateResponse(request, "message.html", {
        "m": msg, "icon": CHANNEL_ICONS.get(msg["channel"], "📨"),
    })


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    from mockpost.routers.api_config import _config
    conf = _config()
    return templates.TemplateResponse(request, "config.html", {
        "config": conf, "names": CHANNEL_NAMES,
    })


@router.get("/webhooks", response_class=HTMLResponse)
async def webhooks_page(request: Request, channel: str | None = None, app: str | None = None):
    from mockpost.apps import get_app_by_name
    app_obj = await get_app_by_name(app) if app else None
    whs = await list_webhooks(channel, app_obj["id"] if app_obj else None)
    apps = await list_apps()
    return templates.TemplateResponse(request, "webhooks.html", {
        "webhooks": whs, "channels": list(WEBHOOK_CHANNELS),
        "names": CHANNEL_NAMES, "current_channel": channel or "",
        "apps": apps, "current_app": app or "", "app_names": {a["id"]: a["name"] for a in apps},
    })


@router.get("/apps", response_class=HTMLResponse)
async def apps_page(request: Request):
    apps = await list_apps()
    return templates.TemplateResponse(request, "apps.html", {
        "apps": apps, "names": CHANNEL_NAMES,
    })
