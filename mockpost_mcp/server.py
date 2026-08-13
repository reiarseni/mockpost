"""MockPost MCP server: consumes the internal /api/* HTTP API.

Transport: stdio, long-lived process. Claude Code setup:
.mcp.json -> { "command": "python", "args": ["-m", "mockpost_mcp.server"] }
"""

from __future__ import annotations

import logging
import os
from typing import Any

# Silence dependency warnings: logging to stdout would break the stdio protocol
logging.disable(logging.WARNING)

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("MOCKPOST_URL", "http://localhost:8090")
TIMEOUT = 10.0

mcp = FastMCP("mockpost")

# In-memory state (persists for the agent's session)
_state: dict[str, Any] = {}


def _headers(app: str | None = None) -> dict[str, str]:
    headers = {}
    if _state.get("test_id"):
        headers["X-MockPost-Test-ID"] = _state["test_id"]
    if app:
        headers["X-MockPost-App"] = app
    elif _state.get("app"):
        headers["X-MockPost-App"] = _state["app"]
    return headers


def _get(path: str, params: dict | None = None, app: str | None = None) -> Any:
    with httpx.Client(timeout=TIMEOUT) as c:
        return c.get(f"{BASE_URL}{path}", params=params, headers=_headers(app)).json()


def _post(path: str, body: dict | None = None, app: str | None = None) -> Any:
    with httpx.Client(timeout=TIMEOUT) as c:
        return c.post(f"{BASE_URL}{path}", json=body, headers=_headers(app)).json()


def _delete(path: str, params: dict | None = None, app: str | None = None) -> Any:
    with httpx.Client(timeout=TIMEOUT) as c:
        return c.delete(f"{BASE_URL}{path}", params=params, headers=_headers(app)).json()


# ---- Session state ----

@mcp.tool()
def set_test_id(test_id: str | None) -> str:
    """Set the active test_id: all subsequent calls are filtered/persisted with it.
    Pass null/None to go back to the global queue."""
    _state["test_id"] = test_id
    return f"active test_id: {test_id or '(global)'}"


@mcp.tool()
def set_app(app: str | None) -> str:
    """Set the active app (a name registered in MockPost): incoming event simulations
    and queries are filtered/delivered only to that app. Pass null/None for no app.
    Register apps with register_app."""
    _state["app"] = app
    return f"active app: {app or '(none)'}"


# ---- Apps (credentials -> identity) ----

@mcp.tool()
def register_app(name: str, creds: dict | None = None) -> dict:
    """Register or update an app: bind its FAKE credentials (Telegram bot token,
    Twilio SID, Stripe sk_test_, WhatsApp phone_id, FCM project_id) to a name.
    The app talks to MockPost using those credentials as if it were the real
    service; MockPost identifies it by them. Use the same name to update creds."""
    return _post("/api/apps", {"name": name, "creds": creds or {}})


@mcp.tool()
def list_apps() -> list[dict]:
    """List registered apps with their fake credentials (MockPost identity)."""
    return _get("/api/apps")


@mcp.tool()
def delete_app(app_id: str) -> dict:
    """Delete a registered app. Its webhooks become global."""
    return _delete(f"/api/apps/{app_id}")


@mcp.tool()
def list_webhook_deliveries(channel: str | None = None, app: str | None = None,
                            limit: int = 50) -> list[dict]:
    """Webhook delivery history: what each app returned (code + body), even if it
    was down (response_code 0). Filterable by channel and app."""
    params = {"limit": min(limit, 200)}
    if channel:
        params["channel"] = channel
    if app:
        params["app"] = app
    return _get("/api/webhooks/deliveries", params)


# ---- Inspection ----

@mcp.tool()
def list_sent_messages(channel: str | None = None, limit: int = 20,
                       status: str | None = None, test_id: str | None = None,
                       app: str | None = None) -> list[dict]:
    """List captured messages for a channel (or all), newest first.
    channel: mail|telegram|whatsapp|webpush|sms|fcm|apns|slack|discord|stripe
    app: registered app name to filter only its messages."""
    params = {"limit": min(limit, 500)}
    if channel:
        params["channel"] = channel
    if status:
        params["status"] = status
    if test_id:
        params["test_id"] = test_id
    if app:
        params["app"] = app
    return _get("/api/messages", params)


@mcp.tool()
def get_message_detail(message_id: str) -> dict:
    """Return a message's full payload, including raw_payload (MIME/JSON)."""
    return _get(f"/api/messages/{message_id}")


# ---- Simulation ----

@mcp.tool()
def simulate_delivery_webhook(message_id: str, status: str) -> dict:
    """Fire a delivery status webhook (delivered|read|failed) back to the app.
    Uses POST /whatsapp/simulate/status."""
    return _post("/whatsapp/simulate/status", {"message_id": message_id, "status": status})


@mcp.tool()
def simulate_incoming_message(channel: str, sender: str, text: str,
                              extra: dict | None = None, app: str | None = None) -> dict:
    """Simulate an external user sending an inbound message to the app.
    channel: telegram (via /telegram/client/sendMessage) or whatsapp.
    app: registered app name to target; overrides set_app for this call."""
    if channel == "telegram":
        return _post("/telegram/client/sendMessage", {"chat_id": sender, "text": text, **(extra or {})}, app=app)
    if channel == "whatsapp":
        return _post("/whatsapp/simulate/incoming", {"from": sender, "text": text, **(extra or {})}, app=app)
    return {"error": f"channel not supported for inbound simulation: {channel}"}


@mcp.tool()
def simulate_stripe_event(event_type: str, overrides: dict | None = None, app: str | None = None) -> dict:
    """Build and send a simulated Stripe event, signed (Stripe-Signature), to the registered webhook.
    app: registered app name to target; overrides set_app for this call."""
    return _post("/stripe/simulate_event", {"event_type": event_type, "overrides": overrides or {}}, app=app)


# ---- Social auth webhooks (GitHub / Facebook / X) ----

@mcp.tool()
def simulate_github_event(event_type: str = "push", payload: dict | None = None,
                          app: str | None = None) -> dict:
    """Fire a GitHub webhook event (push, issues, pull_request) signed with
    X-Hub-Signature-256 to the app's registered GitHub webhook.
    app: registered app name to target; overrides set_app for this call."""
    return _post("/github/simulate", {"event_type": event_type, "payload": payload or {}}, app=app)


@mcp.tool()
def simulate_facebook_event(event_type: str = "page", payload: dict | None = None,
                            app: str | None = None) -> dict:
    """Fire a Facebook Graph API webhook event signed with X-Hub-Signature-256
    to the app's registered Facebook webhook.
    app: registered app name to target; overrides set_app for this call."""
    return _post("/facebook/simulate", {"event_type": event_type, "payload": payload or {}}, app=app)


@mcp.tool()
def simulate_x_event(event_type: str = "tweet_create_events", payload: list | None = None,
                     app: str | None = None) -> dict:
    """Fire an X (Twitter) Account Activity webhook event signed with
    X-Twitter-Webhooks-Signature to the app's registered X webhook.
    payload is a list of event objects, as the real API delivers.
    app: registered app name to target; overrides set_app for this call."""
    return _post("/x/simulate", {"event_type": event_type, "payload": payload or []}, app=app)


@mcp.tool()
def verify_facebook_webhook() -> str:
    """Verify a Facebook webhook subscription (hub.mode/hub.verify_token/
    hub.challenge) as Meta does on registration. Returns the challenge URL."""
    return (f"{BASE_URL}/facebook/webhook?hub.mode=subscribe"
            f"&hub.verify_token=<verify_token>&hub.challenge=<challenge>")


# ---- OTP ----

@mcp.tool()
def get_latest_otp(identifier: str, channel: str = "any", test_id: str | None = None) -> dict:
    """Return the latest OTP code (SMS or email) sent to an identifier."""
    params = {"identifier": identifier, "channel": channel}
    if test_id:
        params["test_id"] = test_id
    return _get("/api/otp/latest", params)


@mcp.tool()
def generate_totp_secret(identifier: str) -> dict:
    """Generate and store a TOTP secret (Google Authenticator). Returns base32 secret and otpauth:// URL."""
    return _post("/api/otp/totp/generate", {"identifier": identifier})


@mcp.tool()
def get_totp_code(identifier: str) -> dict:
    """Compute the current TOTP code (6 digits) for a previously generated secret. Window ±1."""
    return _get("/api/otp/totp/code", {"identifier": identifier})


# ---- OAuth ----

@mcp.tool()
def set_oauth_fake_profile(provider: str, profile: dict) -> dict:
    """Set the profile the fake OAuth provider (google|github|facebook|x) returns on the next login."""
    return _post("/api/oauth/profile", {"provider": provider, "profile": profile})


@mcp.tool()
def get_oauth_session(session_id: str) -> dict:
    """Inspect a simulated OAuth session: code, tokens, returned profile and expiry."""
    return _get(f"/api/oauth/sessions/{session_id}")


# ---- Config / webhooks / cleanup ----

@mcp.tool()
def get_channel_config(channel: str) -> dict:
    """Return host/port/base URL/fake tokens the app must use for that channel."""
    return _get(f"/api/config/{channel}")


@mcp.tool()
def register_webhook(channel: str, target_url: str, token: str | None = None,
                     config: dict | None = None, app: str | None = None) -> dict:
    """Register an app webhook (Telegram setWebhook, WhatsApp, Stripe...).
    If you pass an app (registered name), the webhook only receives events from that app."""
    return _post("/api/webhooks", {"channel": channel, "target_url": target_url,
                                   "token": token, "config": config or {}, "app": app})


@mcp.tool()
def list_webhooks(channel: str | None = None, app: str | None = None) -> list[dict]:
    """List registered webhooks, optionally filtered by channel and app."""
    params: dict = {}
    if channel:
        params["channel"] = channel
    if app:
        params["app"] = app
    return _get("/api/webhooks", params)


@mcp.tool()
def trigger_webhook(webhook_id: str, event_type: str = "test", payload: dict | None = None) -> dict:
    """Fire a test event to a registered webhook and return the app's response."""
    return _post(f"/api/webhooks/{webhook_id}/trigger", {"event_type": event_type, "payload": payload or {}})


@mcp.tool()
def clear_channel(channel: str, test_id: str | None = None, app: str | None = None) -> dict:
    """Delete all captured messages of a channel (cleanup between test runs).
    With app, only that app's messages."""
    params = {"channel": channel}
    if test_id:
        params["test_id"] = test_id
    if app:
        params["app"] = app
    return _delete("/api/messages", params)


@mcp.tool()
def clear_all(test_id: str | None = None, app: str | None = None) -> dict:
    """Delete all captured messages (or only those of a test_id/app)."""
    params = {}
    if test_id:
        params["test_id"] = test_id
    if app:
        params["app"] = app
    return _delete("/api/messages", params)


# ---- Timeline ----

@mcp.tool()
def get_timeline_markdown(since: str | None = None, channels: list[str] | None = None,
                          limit: int = 100, test_id: str | None = None,
                          app: str | None = None) -> str:
    """FULL TIMELINE as Markdown: messages + webhook_events + stripe_events in
    chronological order. Call this first when verifying a test result; use
    get_message_detail only for a single event's detail. With app, only that app's events."""
    params: dict = {"limit": min(limit, 1000)}
    if since:
        params["since"] = since
    if channels:
        params["channels"] = channels
    if test_id:
        params["test_id"] = test_id
    if app:
        params["app"] = app
    with httpx.Client(timeout=TIMEOUT) as c:
        return c.get(f"{BASE_URL}/api/timeline/markdown", params=params, headers=_headers()).text


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
