"""FCM HTTP v1 and APNs provider API fidelity."""

from __future__ import annotations

import json

DEVICE_TOKEN = "a" * 64
PROJECT = "demo-project"
AUTH = {"Authorization": "Bearer ya29.fake-oauth-token"}


def fcm_send(client, message: dict, **extra):
    return client.post(f"/fcm/v1/projects/{PROJECT}/messages:send",
                       headers=AUTH, json={"message": message, **extra})


def test_fcm_accepts_a_token_message_and_returns_a_message_name(client):
    r = fcm_send(client, {"token": "device-token-1",
                          "notification": {"title": "Hi", "body": "there"}})
    assert r.status_code == 200
    assert r.json()["name"].startswith(f"projects/{PROJECT}/messages/")

    msg = client.get("/api/messages", params={"channel": "fcm"}).json()[0]
    assert msg["body"] == "there"
    assert json.loads(msg["meta"])["target"] == "token"


def test_fcm_rejects_two_targets_with_the_google_error_envelope(client):
    r = fcm_send(client, {"token": "t", "topic": "news", "notification": {"body": "x"}})
    assert r.status_code == 400
    error = r.json()["error"]
    assert error["status"] == "INVALID_ARGUMENT"
    assert error["code"] == 400


def test_fcm_requires_a_bearer_token(client):
    r = client.post(f"/fcm/v1/projects/{PROJECT}/messages:send",
                    json={"message": {"token": "t", "notification": {"body": "x"}}})
    assert r.status_code == 401
    assert r.json()["error"]["status"] == "UNAUTHENTICATED"


def test_fcm_validate_only_does_not_capture_the_message(client):
    r = fcm_send(client, {"token": "t", "notification": {"body": "dry run"}}, validate_only=True)
    assert r.status_code == 200
    assert client.get("/api/messages", params={"channel": "fcm"}).json() == []


def test_fcm_unregistered_token_answers_404(client):
    client.post("/fcm/simulate/unregister", json={"token": "dead-token"})
    r = fcm_send(client, {"token": "dead-token", "notification": {"body": "x"}})
    assert r.status_code == 404
    assert r.json()["error"]["status"] == "UNREGISTERED"


def test_apns_returns_200_with_no_body_and_an_apns_id(client):
    r = client.post(f"/apns/3/device/{DEVICE_TOKEN}",
                    headers={"apns-topic": "com.test.app", "apns-push-type": "alert"},
                    json={"aps": {"alert": {"title": "Hi", "body": "there"}, "badge": 1}})
    assert r.status_code == 200
    assert r.content == b""
    assert r.headers["apns-id"]

    msg = client.get("/api/messages", params={"channel": "apns"}).json()[0]
    assert msg["body"] == "there"
    meta = json.loads(msg["meta"])
    assert meta["topic"] == "com.test.app"
    assert meta["push_type"] == "alert"


def test_apns_echoes_a_client_supplied_apns_id(client):
    given = "eabeae54-14a8-11e5-b60b-1697f925ec7b"
    r = client.post(f"/apns/3/device/{DEVICE_TOKEN}", headers={"apns-id": given},
                    json={"aps": {"alert": "hi"}})
    assert r.headers["apns-id"] == given


def test_apns_unregistered_device_answers_410(client):
    client.post("/apns/simulate/unregister", json={"device_token": DEVICE_TOKEN})
    r = client.post(f"/apns/3/device/{DEVICE_TOKEN}", json={"aps": {"alert": "hi"}})
    assert r.status_code == 410
    assert r.json()["reason"] == "Unregistered"


def test_apns_rejects_a_payload_over_4kb(client):
    r = client.post(f"/apns/3/device/{DEVICE_TOKEN}",
                    json={"aps": {"alert": "x" * 5000}})
    assert r.status_code == 413
    assert r.json()["reason"] == "PayloadTooLarge"
