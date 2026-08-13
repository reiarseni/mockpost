"""Web Push fidelity: MockPost as the push service a real backend talks to."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

pywebpush = pytest.importorskip("pywebpush")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def vapid_keys() -> dict:
    """A VAPID key pair in the format pywebpush expects (raw, base64url)."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint)
    return {"private": b64url(private_raw), "public": b64url(public)}


def send_push(subscription: dict, payload: str, **kwargs):
    return pywebpush.webpush(
        subscription_info={"endpoint": subscription["endpoint"], "keys": subscription["keys"]},
        data=payload,
        vapid_private_key=vapid_keys()["private"],
        vapid_claims={"sub": "mailto:app@test.com"},
        **kwargs,
    )


def test_subscribe_returns_a_browser_shaped_subscription(client):
    sub = client.post("/webpush/subscribe").json()
    assert sub["endpoint"].endswith(f"/webpush/push/{sub['id']}")
    assert sub["expirationTime"] is None
    assert sub["keys"]["p256dh"] and sub["keys"]["auth"]
    assert sub["vapid_public_key"]


def test_real_encrypted_push_is_accepted_and_decrypted(client):
    sub = client.post("/webpush/subscribe").json()
    payload = json.dumps({"title": "Persona identificada", "body": "cámara E2ETESTCAM"})

    response = send_push(sub, payload, ttl=120)
    assert response.status_code == 201

    msg = client.get("/api/messages", params={"channel": "webpush"}).json()[0]
    assert json.loads(msg["body"])["body"] == "cámara E2ETESTCAM"
    meta = json.loads(msg["meta"])
    assert meta["content_encoding"] == "aes128gcm"
    assert meta["decryption"] == "decrypted"
    assert meta["ttl"] == "120"
    assert meta["encrypted_bytes"] > 0


def test_push_without_vapid_is_rejected(client):
    sub = client.post("/webpush/subscribe").json()
    r = client.post(sub["endpoint"], content=b"whatever",
                    headers={"Content-Encoding": "aes128gcm"})
    assert r.status_code == 401


def test_push_with_a_foreign_audience_is_rejected(client):
    """A JWT signed for another push service must not be accepted here."""
    sub = client.post("/webpush/subscribe").json()
    from py_vapid import Vapid02
    vapid = Vapid02.from_string(vapid_keys()["private"])
    header = vapid.sign({"aud": "https://fcm.googleapis.com", "sub": "mailto:app@test.com",
                         "exp": 2000000000})["Authorization"]
    r = client.post(sub["endpoint"], content=b"whatever",
                    headers={"Content-Encoding": "aes128gcm", "Authorization": header})
    assert r.status_code == 401


def test_unsupported_content_encoding_is_rejected(client):
    sub = client.post("/webpush/subscribe").json()
    from py_vapid import Vapid02
    vapid = Vapid02.from_string(vapid_keys()["private"])
    audience = str(client.base_url).rstrip("/")
    header = vapid.sign({"aud": audience, "sub": "mailto:app@test.com",
                         "exp": 2000000000})["Authorization"]
    r = client.post(sub["endpoint"], content=b"whatever",
                    headers={"Content-Encoding": "gzip", "Authorization": header})
    assert r.status_code == 415


def test_expired_subscription_answers_410(client):
    sub = client.post("/webpush/subscribe").json()
    assert client.post(f"/webpush/subscriptions/{sub['id']}/expire").json()["status"] == "gone"

    with pytest.raises(pywebpush.WebPushException) as exc:
        send_push(sub, "payload")
    assert exc.value.response.status_code == 410


def test_push_to_unknown_subscription_answers_404(client):
    r = client.post("/webpush/push/does-not-exist", content=b"x")
    assert r.status_code == 404


def test_client_supplied_keys_are_stored_and_left_encrypted(client):
    """A subscription created with foreign keys cannot be decrypted, and the
    ciphertext is kept instead of being lost."""
    key = ec.generate_private_key(ec.SECP256R1())
    p256dh = b64url(key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint))
    sub = client.post("/webpush/subscribe",
                      json={"keys": {"p256dh": p256dh, "auth": b64url(b"0123456789abcdef")}}).json()

    assert send_push(sub, "secret payload").status_code == 201
    msg = client.get("/api/messages", params={"channel": "webpush"}).json()[0]
    meta = json.loads(msg["meta"])
    assert "no private key" in meta["decryption"]
    assert meta["encrypted_bytes"] > 0


def test_send_shortcut_still_works(client):
    """The JSON envelope endpoint stays supported for existing callers."""
    from py_vapid import Vapid02
    vapid = Vapid02.from_string(vapid_keys()["private"])
    audience = str(client.base_url).rstrip("/")
    header = vapid.sign({"aud": audience, "sub": "mailto:app@test.com",
                         "exp": 2000000000})["Authorization"]
    r = client.post("/webpush/send", headers={"Authorization": header}, json={
        "subscription": {"endpoint": "http://example.test/ep", "keys": {"p256dh": "x", "auth": "y"}},
        "payload": "hello",
    })
    assert r.json()["ok"] is True
