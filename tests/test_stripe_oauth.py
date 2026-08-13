"""Stripe object shapes and OAuth2/OIDC error and token contracts."""

from __future__ import annotations

import re

import jwt

from mockpost.config import settings

STRIPE_AUTH = {"Authorization": "Bearer sk_test_51Fake"}


def test_checkout_session_has_the_real_object_shape(client):
    r = client.post("/stripe/v1/checkout/sessions", headers=STRIPE_AUTH, data={
        "mode": "payment", "success_url": "https://app.test/ok",
        "cancel_url": "https://app.test/ko", "amount_total": "2500",
        "currency": "eur", "customer_email": "buyer@test.com",
        "metadata[order_id]": "A-42",
    })
    assert r.status_code == 200
    session = r.json()
    assert re.fullmatch(r"cs_test_[0-9a-f]{24}", session["id"])
    assert session["object"] == "checkout.session"
    assert session["payment_status"] == "unpaid"
    assert session["metadata"] == {"order_id": "A-42"}
    assert session["created"] and session["expires_at"] > session["created"]
    assert session["url"].endswith(session["id"])


def test_payment_intent_carries_a_client_secret(client):
    r = client.post("/stripe/v1/payment_intents", headers=STRIPE_AUTH,
                    data={"amount": "1999", "currency": "eur", "metadata[cart]": "9"})
    pi = r.json()
    assert re.fullmatch(r"pi_test_[0-9a-f]{24}", pi["id"])
    assert pi["object"] == "payment_intent"
    assert pi["status"] == "requires_payment_method"
    assert pi["client_secret"].startswith(f"{pi['id']}_secret_")
    assert pi["metadata"] == {"cart": "9"}


def test_payment_intent_rejects_a_zero_amount(client):
    r = client.post("/stripe/v1/payment_intents", headers=STRIPE_AUTH, data={"amount": "0"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "parameter_invalid_integer"


def test_authorize_without_redirect_uri_is_an_oauth_error(client):
    r = client.get("/oauth/google/authorize", params={"client_id": "abc"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_authorize_without_client_id_redirects_with_the_error(client):
    r = client.get("/oauth/google/authorize",
                   params={"redirect_uri": "https://app.test/cb", "state": "xyz"},
                   follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "error=invalid_request" in r.headers["location"]
    assert "state=xyz" in r.headers["location"]


def _authorize(client, scope: str = "openid email"):
    r = client.get("/oauth/google/authorize",
                   params={"client_id": "client-123", "redirect_uri": "https://app.test/cb",
                           "scope": scope, "state": "xyz"},
                   follow_redirects=False)
    return re.search(r"code=([0-9a-f]+)", r.headers["location"]).group(1)


def test_token_exchange_returns_an_id_token_for_openid_scope(client):
    code = _authorize(client)
    r = client.post("/oauth/google/token", data={"grant_type": "authorization_code", "code": code,
                                                 "client_id": "client-123"})
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] > 0
    claims = jwt.decode(body["id_token"], settings.oauth_jwt_key, algorithms=["HS256"],
                        audience="client-123")
    assert claims["email"] == "user@test.com"
    assert claims["aud"] == "client-123"


def test_token_endpoint_accepts_json_and_refresh_grants(client):
    code = _authorize(client, scope="email")
    first = client.post("/oauth/google/token",
                        json={"grant_type": "authorization_code", "code": code}).json()
    assert "id_token" not in first  # no openid scope, no id_token

    refreshed = client.post("/oauth/google/token",
                            data={"grant_type": "refresh_token",
                                  "refresh_token": first["refresh_token"]}).json()
    assert refreshed["access_token"]


def test_unsupported_grant_type_and_bad_code(client):
    r = client.post("/oauth/google/token", data={"grant_type": "password"})
    assert r.json()["error"] == "unsupported_grant_type"
    r = client.post("/oauth/google/token", data={"grant_type": "authorization_code", "code": "no"})
    assert r.json()["error"] == "invalid_grant"


def test_userinfo_401_matches_each_provider(client):
    assert client.get("/oauth/google/userinfo").json()["error"]["status"] == "UNAUTHENTICATED"
    assert client.get("/oauth/github/user").json()["message"] == "Bad credentials"
    assert client.get("/oauth/facebook/me").json()["error"]["code"] == 190
