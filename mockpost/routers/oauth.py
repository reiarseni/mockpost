"""Fake OAuth2 providers for Google, GitHub, Facebook and X (Twitter).

Authorization Code flow with local JWT tokens. The userinfo endpoints
replicate the real response shape of each provider so the app's SDK
parses them like production.
"""

from __future__ import annotations

import json
import time
import uuid

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from mockpost.config import settings, expire_at
from mockpost.db import get_db
from mockpost.request_ctx import get_test_id

router = APIRouter(prefix="/oauth", tags=["oauth"])

# Per-provider emulation routes (matching the real API shape)
_PROVIDERS = {
    "google": {"authorize": "/oauth/google/authorize", "token": "/oauth/google/token",
               "userinfo": "/oauth/google/userinfo"},
    "github": {"authorize": "/oauth/github/authorize", "token": "/oauth/github/token",
               "userinfo": "/oauth/github/user"},
    "facebook": {"authorize": "/oauth/facebook/authorize", "token": "/oauth/facebook/token",
                 "userinfo": "/oauth/facebook/me"},
    "x": {"authorize": "/oauth/x/authorize", "token": "/oauth/x/token",
          "userinfo": "/oauth/x/2/users/me"},
}


def _jwt(payload: dict) -> str:
    payload = {**payload, "iat": int(time.time()), "exp": int(time.time()) + settings.oauth_token_ttl_minutes * 60}
    return jwt.encode(payload, settings.oauth_jwt_key, algorithm="HS256")


def oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    """RFC 6749 error object, the shape every OAuth client parses."""
    return JSONResponse({"error": error, "error_description": description}, status_code=status)


@router.get("/{provider}/authorize")
async def authorize(provider: str, request: Request):
    client_id = request.query_params.get("client_id", "")
    redirect_uri = request.query_params.get("redirect_uri", "")
    scope = request.query_params.get("scope", "")
    state = request.query_params.get("state", "")
    # RFC 6749 4.1.2.1: with no usable redirect_uri the error must be shown to
    # the user, never redirected; with one, the error travels in the redirect.
    if not redirect_uri:
        return oauth_error("invalid_request", "Missing required parameter: redirect_uri")
    if not client_id:
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(
            f"{redirect_uri}{sep}error=invalid_request"
            f"&error_description=Missing+required+parameter%3A+client_id&state={state}")
    code = uuid.uuid4().hex[:24]
    db = get_db()
    session_id = str(uuid.uuid4())
    profile = settings.default_oauth_profile.get(provider, {})
    await db.execute(
        "INSERT INTO oauth_sessions (id, provider, client_id, redirect_uri, code, fake_user_profile, scope, state, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)",
        (session_id, provider, client_id, redirect_uri, code, json.dumps(profile), scope, state, expire_at(10)),
    )
    await db.commit()
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}code={code}&state={state}")


async def _token_params(request: Request) -> dict:
    """Token requests are form-encoded per RFC 6749, but several SDKs post
    JSON; both are read here."""
    content_type = (request.headers.get("Content-Type") or "").split(";")[0].strip()
    if content_type == "application/json":
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return dict(await request.form())


@router.post("/{provider}/token")
async def token(provider: str, request: Request):
    params = await _token_params(request)
    grant_type = params.get("grant_type", "authorization_code")
    db = get_db()

    if grant_type == "refresh_token":
        cur = await db.execute(
            "SELECT * FROM oauth_sessions WHERE provider=? AND refresh_token=? "
            "ORDER BY created_at DESC LIMIT 1", (provider, params.get("refresh_token", "")))
    elif grant_type == "authorization_code":
        cur = await db.execute(
            "SELECT * FROM oauth_sessions WHERE provider=? AND code=? "
            "ORDER BY created_at DESC LIMIT 1", (provider, params.get("code", "")))
    else:
        return oauth_error("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")

    row = await cur.fetchone()
    if not row:
        return oauth_error("invalid_grant", "The provided authorization grant is invalid")

    profile = json.loads(row["fake_user_profile"])
    sub = profile.get("sub") or profile.get("id")
    access_token = _jwt({"sub": str(sub), "provider": provider})
    refresh_token = uuid.uuid4().hex
    await db.execute("UPDATE oauth_sessions SET access_token=?, refresh_token=? WHERE id=?",
                     (access_token, refresh_token, row["id"]))
    await db.commit()
    response = {"access_token": access_token, "token_type": "Bearer",
                "expires_in": settings.oauth_token_ttl_minutes * 60,
                "refresh_token": refresh_token, "scope": row["scope"] or ""}
    # OpenID Connect: an openid scope must come back with an id_token.
    if "openid" in (row["scope"] or ""):
        response["id_token"] = _jwt({
            "iss": settings.mockpost_url, "aud": row["client_id"], "sub": str(sub),
            "email": profile.get("email"), "email_verified": profile.get("email_verified", True),
            "name": profile.get("name"), "picture": profile.get("picture"),
        })
    return response


async def _profile_for(provider: str, access_token: str) -> dict:
    """Return the session profile, shaped like the provider's response."""
    db = get_db()
    cur = await db.execute("SELECT * FROM oauth_sessions WHERE provider=? AND access_token=? ORDER BY created_at DESC LIMIT 1",
                           (provider, access_token))
    row = await cur.fetchone()
    profile = json.loads(row["fake_user_profile"]) if row else settings.default_oauth_profile.get(provider, {})
    if provider == "google":
        return profile  # {sub, email, email_verified, name, picture}
    if provider == "github":
        return {**profile, "id": str(profile.get("id", 0))}  # {id, login, name, email, avatar_url}
    if provider == "facebook":
        # Graph API /me: {id, name, email, picture:{data:{url}}}
        return {"id": str(profile.get("id", 0)), "name": profile.get("name", ""),
                "email": profile.get("email", ""), "picture": profile.get("picture", {})}
    if provider == "x":
        # X API v2 /2/users/me: {data:{id, name, username}}
        return {"data": {"id": str(profile.get("id", 0)), "name": profile.get("name", ""),
                         "username": profile.get("username", "")}}
    return profile


async def _check_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        jwt.decode(token, settings.oauth_jwt_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if token in settings.revoked_oauth_tokens:
        return None
    return token


def unauthorized(provider: str) -> JSONResponse:
    """Each provider words its 401 differently and SDKs match on that text."""
    if provider == "google":
        return JSONResponse({"error": {"code": 401, "message": "Invalid Credentials",
                                       "status": "UNAUTHENTICATED"}}, status_code=401)
    if provider == "github":
        return JSONResponse({"message": "Bad credentials",
                             "documentation_url": "https://docs.github.com/rest"},
                            status_code=401)
    if provider == "facebook":
        return JSONResponse({"error": {"message": "Invalid OAuth access token",
                                       "type": "OAuthException", "code": 190}}, status_code=401)
    return JSONResponse({"title": "Unauthorized", "status": 401,
                         "detail": "Unauthorized"}, status_code=401)


@router.get("/{provider}/userinfo")
@router.get("/{provider}/user")
@router.get("/{provider}/me")
async def userinfo(provider: str, request: Request):
    access_token = await _check_bearer(request)
    if not access_token:
        return unauthorized(provider)
    return await _profile_for(provider, access_token)


@router.get("/x/2/users/me")
async def x_users_me(request: Request):
    access_token = await _check_bearer(request)
    if not access_token:
        return unauthorized("x")
    return await _profile_for("x", access_token)
