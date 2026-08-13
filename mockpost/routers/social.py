"""Social auth webhooks: GitHub, Facebook and X (Twitter) replicating each
provider's real delivery mechanics, plus Google's tokeninfo/revoke (OAuth has
no webhooks there).

Mechanics replicated:
- GitHub:   X-GitHub-Event + X-Hub-Signature-256 (HMAC-SHA256 with secret)
- Facebook: GET hub.mode/hub.verify_token/hub.challenge verification +
            X-Hub-Signature-256 (HMAC-SHA256 with app secret)
- X:        CRC check (crc_token -> response_token HMAC) +
            X-Twitter-Webhooks-Signature (base64 HMAC-SHA256)
- Google:   tokeninfo + revoke endpoints (no webhooks by design)
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from mockpost.config import settings, utcnow
from mockpost.db import get_db
from mockpost.request_ctx import get_app_id, get_test_id
from mockpost.signing import (
    facebook_signature,
    github_signature,
    x_crc_response,
    x_signature,
)
from mockpost.store import register_webhook
from mockpost.webhooks import deliver_webhook

router = APIRouter(tags=["social"])

SOCIAL_CHANNELS = ("github", "facebook", "x")


async def _secret_for(app_id: str, provider: str) -> str:
    """Signing secret for the social webhook.

    If the app registered its webhook with its own secret/token (e.g. the
    GitHub config.secret), that one is used — just like in production the app
    knows its secret and can verify the signature. Otherwise a random secret
    is generated, stable per app+provider."""
    db = get_db()
    cur = await db.execute(
        "SELECT token FROM webhooks_registry WHERE channel=? AND app_id=? ORDER BY created_at DESC LIMIT 1",
        (provider, app_id))
    row = await cur.fetchone()
    if row and row["token"]:
        return row["token"]
    key = f"{app_id}:{provider}"
    if key not in settings.social_webhook_secrets:
        settings.social_webhook_secrets[key] = uuid.uuid4().hex
    return settings.social_webhook_secrets[key]


async def _deliver_social(channel: str, provider: str, event_type: str,
                          payload: dict, request: Request, signature: str) -> dict:
    """Deliver the event to the registered webhook of that channel for the active app."""
    app_id = await get_app_id(request)
    if not app_id:
        raise HTTPException(status_code=400, detail="header X-MockPost-App required to deliver a social webhook")
    db = get_db()
    cur = await db.execute(
        "SELECT * FROM webhooks_registry WHERE channel=? AND app_id=? ORDER BY created_at DESC LIMIT 1",
        (channel, app_id))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"no {channel} webhook registered for this app")
    return await deliver_webhook(channel, row["target_url"], event_type, payload,
                                 headers={"X-MockPost-App": app_id, "X-Social-Signature": signature},
                                 test_id=get_test_id(request), app_id=app_id)


# ---- GitHub ----

@router.post("/github/repos/{owner}/{repo}/hooks")
async def github_create_hook(owner: str, repo: str, request: Request):
    """Replica of POST /repos/{owner}/{repo}/hooks: registers the app webhook."""
    data = await request.json()
    config = data.get("config", {})
    url = config.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="config.url required")
    app_id = await get_app_id(request)
    await register_webhook("github", url, token=config.get("secret"),
                           config={"owner": owner, "repo": repo}, app_id=app_id)
    hook_id = uuid.uuid4().hex[:12]
    return {"id": hook_id, "type": "Repository", "url": url,
            "config": {**config, "secret": "********"}, "active": True,
            "events": data.get("events", ["push"])}


@router.post("/github/simulate")
async def github_simulate(request: Request):
    """Fire a GitHub webhook event (push, issues, pull_request) with a real signature."""
    data = await request.json()
    event_type = data.get("event_type", "push")
    payload = data.get("payload", {"ref": "refs/heads/main", "repository": {"full_name": "user/repo"}})
    body = json.dumps(payload, ensure_ascii=False)
    app_id = await get_app_id(request)
    signature = github_signature(body, await _secret_for(app_id, "github"))
    result = await _deliver_social("github", "github", event_type, payload, request, signature)
    return {"ok": True, "event": event_type, "signature": signature, "delivered": result}


# ---- Facebook ----

@router.get("/facebook/webhook")
async def facebook_verify(request: Request):
    """Real Meta webhook verification: hub.mode + hub.verify_token + hub.challenge."""
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and verify_token:
        return PlainTextResponse(challenge or "")
    raise HTTPException(status_code=403, detail="verify failed")


@router.post("/facebook/simulate")
async def facebook_simulate(request: Request):
    """Fire a Facebook webhook event (page, messaging) with a real X-Hub-Signature-256."""
    data = await request.json()
    event_type = data.get("event_type", "page")
    payload = data.get("payload", {"object": "page", "entry": [{"id": "page_1", "time": 0}]})
    body = json.dumps(payload, ensure_ascii=False)
    app_id = await get_app_id(request)
    signature = facebook_signature(body, await _secret_for(app_id, "facebook"))
    result = await _deliver_social("facebook", "facebook", event_type, payload, request, signature)
    return {"ok": True, "event": event_type, "signature": signature, "delivered": result}


# ---- X (Twitter) ----

@router.post("/x/webhook")
async def x_register(request: Request):
    """Replica of POST /1.1/account_activity/all/{env}/webhooks.json: registers the webhook."""
    data = await request.json()
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    app_id = await get_app_id(request)
    await register_webhook("x", url, token=data.get("secret"),
                           config={"env": data.get("env", "dev")}, app_id=app_id)
    return {"id": uuid.uuid4().hex[:16], "url": url, "valid": True,
            "created_timestamp": utcnow(), "secret": "********"}


@router.get("/x/webhook/crc")
async def x_crc(request: Request):
    """X (Account Activity API) CRC check: returns the response_token."""
    crc_token = request.query_params.get("crc_token")
    if not crc_token:
        raise HTTPException(status_code=400, detail="crc_token required")
    app_id = await get_app_id(request)
    response_token = x_crc_response(crc_token, await _secret_for(app_id, "x"))
    return {"response_token": f"sha256={response_token}"}


@router.post("/x/simulate")
async def x_simulate(request: Request):
    """Fire an X webhook event (tweet_create, favorite) with a real signature."""
    data = await request.json()
    event_type = data.get("event_type", "tweet_create_events")
    payload = data.get("payload", [{"id": "1", "text": "hello", "user": {"id": "123"}}])
    body = json.dumps(payload, ensure_ascii=False)
    app_id = await get_app_id(request)
    signature = x_signature(body, await _secret_for(app_id, "x"))
    result = await _deliver_social("x", "x", event_type, payload, request, signature)
    return {"ok": True, "event": event_type, "signature": signature, "delivered": result}


# ---- Google (no webhooks; tokeninfo + revoke) ----

@router.post("/oauth/google/tokeninfo")
async def google_tokeninfo(request: Request):
    """Replica of POST https://oauth2.googleapis.com/tokeninfo."""
    form = await request.form()
    access_token = form.get("access_token")
    db = get_db()
    cur = await db.execute("SELECT * FROM oauth_sessions WHERE provider='google' AND access_token=? ORDER BY created_at DESC LIMIT 1",
                           (access_token,))
    row = await cur.fetchone()
    if not row:
        return JSONResponse({"error_description": "Invalid Value"}, status_code=400)
    profile = json.loads(row["fake_user_profile"])
    return {"azp": row["client_id"], "aud": row["client_id"], "sub": str(profile.get("sub", "")),
            "scope": row["scope"] or "openid email profile",
            "expires_in": settings.oauth_token_ttl_minutes * 60, "email": profile.get("email"),
            "email_verified": profile.get("email_verified", True), "name": profile.get("name")}


@router.post("/oauth/google/revoke")
async def google_revoke(request: Request):
    """Replica of POST https://oauth2.googleapis.com/revoke.

    The access_token is a stateless JWT: to make it invalid, it is added to
    the process's revoked list."""
    form = await request.form()
    access_token = form.get("token")
    db = get_db()
    await db.execute("UPDATE oauth_sessions SET access_token=NULL, refresh_token=NULL WHERE access_token=?",
                     (access_token,))
    await db.commit()
    settings.revoked_oauth_tokens.add(access_token)
    return JSONResponse(content={}, status_code=200)
