"""MockPost: multi-channel message emulator for testing + panel + internal API.

Run: uv run mockpost   (or: uvicorn mockpost.main:app)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mockpost import db
from mockpost.config import settings
from mockpost.smtp_server import start_smtp, stop_smtp
from mockpost.routers import (
    api_messages, api_otp, api_oauth, api_webhooks, api_config, api_timeline, api_apps,
    telegram, whatsapp, webpush, twilio, push_native, team_webhooks, stripe, oauth,
    social, panel,
)

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    await start_smtp()
    yield
    await stop_smtp()
    await db.close_db()


app = FastAPI(title="MockPost", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Emulated channel routers
app.include_router(telegram.router)
app.include_router(whatsapp.router)
app.include_router(webpush.router)
app.include_router(twilio.router)
app.include_router(push_native.router)
app.include_router(team_webhooks.router)
app.include_router(stripe.router)
app.include_router(oauth.router)
app.include_router(social.router)

# Internal API /api/* (consumed by MCP and panel)
app.include_router(api_messages.router)
app.include_router(api_otp.router)
app.include_router(api_oauth.router)
app.include_router(api_webhooks.router)
app.include_router(api_config.router)
app.include_router(api_timeline.router)
app.include_router(api_apps.router)

# Web panel
app.include_router(panel.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "http_port": settings.http_port, "smtp_port": settings.smtp_port}
