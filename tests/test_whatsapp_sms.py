"""WhatsApp Cloud API and Twilio fidelity: paths, ids and payload shapes."""

from __future__ import annotations

import json
import re

PHONE_ID = "15550000000"
ACCOUNT_SID = "AC00000000000000000000000000000000"


def test_graph_version_in_the_path_is_accepted(client):
    r = client.post(f"/whatsapp/v21.0/{PHONE_ID}/messages",
                    json={"messaging_product": "whatsapp", "to": "34600111222",
                          "type": "text", "text": {"body": "hola"}})
    assert r.status_code == 200
    body = r.json()
    assert body["messages"][0]["id"].startswith("wamid.")
    assert body["messages"][0]["message_status"] == "accepted"
    assert body["contacts"][0]["wa_id"] == "34600111222"

    msg = client.get("/api/messages", params={"channel": "whatsapp"}).json()[0]
    assert msg["body"] == "hola"
    assert json.loads(msg["meta"])["graph_version"] == "v21.0"


def test_legacy_v1_path_still_works(client):
    r = client.post(f"/whatsapp/v1/{PHONE_ID}/messages",
                    json={"to": "34600111222", "text": {"body": "legacy"}})
    assert r.status_code == 200


def test_template_and_interactive_messages_are_summarized(client):
    client.post(f"/whatsapp/v19.0/{PHONE_ID}/messages",
                json={"messaging_product": "whatsapp", "to": "34600111222", "type": "template",
                      "template": {"name": "order_update", "language": {"code": "es"}}})
    client.post(f"/whatsapp/v19.0/{PHONE_ID}/messages",
                json={"messaging_product": "whatsapp", "to": "34600111222", "type": "interactive",
                      "interactive": {"type": "button", "body": {"text": "Confirmas?"}}})
    bodies = [m["body"] for m in client.get("/api/messages", params={"channel": "whatsapp"}).json()]
    assert "template:order_update" in bodies
    assert "Confirmas?" in bodies


def test_wrong_messaging_product_returns_the_graph_error_envelope(client):
    r = client.post(f"/whatsapp/v19.0/{PHONE_ID}/messages",
                    json={"messaging_product": "sms", "to": "34600111222",
                          "text": {"body": "x"}})
    assert r.status_code == 400
    error = r.json()["error"]
    assert error["code"] == 100
    assert error["fbtrace_id"]


def test_webhook_verification_echoes_the_challenge(client):
    r = client.get("/whatsapp/webhook", params={"hub.mode": "subscribe",
                                                "hub.verify_token": "secret",
                                                "hub.challenge": "1158201444"})
    assert r.status_code == 200
    assert r.text == "1158201444"
    assert client.get("/whatsapp/webhook", params={"hub.mode": "unsubscribe"}).status_code == 403


def test_incoming_simulation_uses_the_cloud_api_envelope(client):
    client.post("/api/apps", json={"name": "wa-app", "creds": {"phone_id": PHONE_ID}})
    client.post("/api/webhooks", json={"channel": "whatsapp", "app": "wa-app",
                                       "target_url": "http://127.0.0.1:9/wa"})
    r = client.post("/whatsapp/simulate/incoming",
                    headers={"X-MockPost-App": "wa-app"},
                    json={"from": "34600999888", "text": "hello there",
                          "phone_number_id": PHONE_ID})
    assert r.json()["ok"] is True

    deliveries = client.get("/api/webhooks/deliveries", params={"channel": "whatsapp"}).json()
    value = deliveries[0]["payload"]
    payload = json.loads(value)
    change = payload["entry"][0]["changes"][0]["value"]
    assert change["messaging_product"] == "whatsapp"
    assert change["metadata"]["phone_number_id"] == PHONE_ID
    assert change["messages"][0]["text"]["body"] == "hello there"


def test_twilio_message_sid_and_response_shape(client):
    r = client.post(f"/twilio/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json",
                    data={"To": "+34600111222", "From": "+15005550006", "Body": "code 4321"})
    assert r.status_code == 200
    body = r.json()
    assert re.fullmatch(r"SM[0-9a-f]{32}", body["sid"])
    assert body["status"] == "queued"
    assert body["api_version"] == "2010-04-01"
    assert body["subresource_uris"]["media"].endswith("/Media.json")

    otp = client.get("/api/otp/latest", params={"identifier": "+34600111222"}).json()
    assert otp["code"] == "4321"


def test_twilio_requires_the_to_number(client):
    r = client.post(f"/twilio/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json",
                    data={"Body": "no recipient"})
    assert r.status_code == 400
    assert r.json()["code"] == 21604


def test_twilio_message_resource_is_readable_over_get(client):
    r = client.get(f"/twilio/2010-04-01/Accounts/{ACCOUNT_SID}/Messages/SMabc.json")
    assert r.status_code == 200
    assert r.json()["sid"] == "SMabc"
