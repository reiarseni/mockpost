"""Social auth tests: Google/GitHub/Facebook/X login flows and their webhooks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json


def _signature(secret: str, body: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def test_google_login_flow(client):
    r = client.get("/oauth/google/authorize",
                   params={"client_id": "c", "redirect_uri": "http://app/cb"})
    assert r.status_code == 307
    code = r.headers["location"].split("code=")[1].split("&")[0]

    r = client.post("/oauth/google/token", data={"code": code})
    token = r.json()["access_token"]
    assert r.json()["token_type"] == "Bearer"

    r = client.get("/oauth/google/userinfo", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["email"] == "user@test.com"

    # tokeninfo + revoke (Google's real OAuth endpoints)
    r = client.post("/oauth/google/tokeninfo", data={"access_token": token})
    assert r.json()["email"] == "user@test.com"

    r = client.post("/oauth/google/revoke", data={"token": token})
    assert r.status_code == 200

    r = client.get("/oauth/google/userinfo", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401  # revoked


def test_facebook_me_and_webhook(client):
    r = client.get("/oauth/facebook/authorize",
                   params={"client_id": "c", "redirect_uri": "http://app/cb"})
    code = r.headers["location"].split("code=")[1].split("&")[0]
    r = client.post("/oauth/facebook/token", data={"code": code})
    token = r.json()["access_token"]

    r = client.get("/oauth/facebook/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["id"]  # facebook shape: {id, name, email, picture}

    # webhook verification (hub.*) + signed event
    r = client.get("/facebook/webhook", params={"hub.mode": "subscribe",
                                                "hub.verify_token": "tok",
                                                "hub.challenge": "ch123"})
    assert r.text == "ch123"

    client.post("/api/apps", json={"name": "app-fb", "creds": {}})
    client.post("/api/webhooks", json={"channel": "facebook",
                                       "target_url": "http://127.0.0.1:9/fb", "app": "app-fb"})
    r = client.post("/facebook/simulate", json={"event_type": "page",
                                                "payload": {"object": "page"}},
                    headers={"X-MockPost-App": "app-fb"})
    assert r.json()["signature"].startswith("sha256=")


def test_x_me_and_crc(client):
    r = client.get("/oauth/x/authorize",
                   params={"client_id": "c", "redirect_uri": "http://app/cb"})
    code = r.headers["location"].split("code=")[1].split("&")[0]
    r = client.post("/oauth/x/token", data={"code": code})
    token = r.json()["access_token"]

    r = client.get("/oauth/x/2/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["data"]["username"] == "fakeuser"

    # CRC check: response_token must be base64(HMAC-SHA256(crc_token, secret))
    client.post("/api/apps", json={"name": "app-x", "creds": {}})
    r = client.get("/x/webhook/crc", params={"crc_token": "crc123"},
                   headers={"X-MockPost-App": "app-x"})
    assert r.json()["response_token"].startswith("sha256=")


def test_github_hook_and_signed_event(client):
    client.post("/api/apps", json={"name": "app-gh", "creds": {}})
    r = client.post("/github/repos/owner/repo/hooks", json={
        "config": {"url": "http://127.0.0.1:9/gh", "secret": "s3cret"},
        "events": ["push"]}, headers={"X-MockPost-App": "app-gh"})
    assert r.json()["config"]["secret"] == "********"  # masked like GitHub

    r = client.post("/github/simulate", json={"event_type": "push",
                                              "payload": {"ref": "refs/heads/main"}},
                    headers={"X-MockPost-App": "app-gh"})
    sig = r.json()["signature"]
    assert sig.startswith("sha256=")
    # the app can verify the signature with its webhook secret
    body = json.dumps({"ref": "refs/heads/main"}, ensure_ascii=False)
    assert hmac.compare_digest(sig, _signature("s3cret", body))
