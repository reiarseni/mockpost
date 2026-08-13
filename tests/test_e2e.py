"""End-to-end tests: channels capture messages, timeline + MCP surface work."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_email_capture_and_otp(client):
    msg = MIMEText("Welcome! Your verification code is 481516")
    msg["Subject"] = "Welcome"
    msg["From"] = "app@test.com"
    msg["To"] = "user@test.com"
    with smtplib.SMTP("localhost", client.smtp_port) as s:
        s.send_message(msg)

    msgs = client.get("/api/messages", params={"channel": "mail"}).json()
    assert len(msgs) == 1
    assert msgs[0]["subject"] == "Welcome"
    assert msgs[0]["direction"] == "outbound"

    otp = client.get("/api/otp/latest", params={"identifier": "user@test.com"}).json()
    assert otp["code"] == "481516"


def test_telegram_send_and_incoming(client):
    r = client.post("/telegram/bot12345/sendMessage",
                    json={"chat_id": 42, "text": "hello"})
    assert r.json()["ok"] is True

    r = client.post("/telegram/bot12345/setWebhook",
                    json={"url": "http://127.0.0.1:9/webhooks/tg"})
    assert r.json()["result"] is True

    r = client.post("/telegram/client/sendMessage",
                    json={"chat_id": 42, "text": "reply"},
                    headers={"X-MockPost-App": "nonexistent"})
    # no app registered -> event captured but not delivered
    assert r.json()["ok"] is True
    assert r.json()["webhooks_delivered"] == []


def test_stripe_signed_event(client):
    r = client.post("/api/webhooks", json={
        "channel": "stripe", "target_url": "http://127.0.0.1:9/webhooks/stripe"})
    assert r.status_code == 200

    r = client.post("/stripe/simulate_event",
                    json={"event_type": "checkout.session.completed"})
    d = r.json()
    assert d["event"]["type"] == "checkout.session.completed"
    assert d["signature"].startswith("t=")


def test_webhook_channel_validation(client):
    r = client.post("/api/webhooks", json={
        "channel": "mail", "target_url": "http://x/"})
    assert r.status_code == 400


def test_app_isolation(client):
    # register two apps with fake telegram tokens
    client.post("/api/apps", json={"name": "app-a", "creds": {"telegram_token": "111:A"}})
    client.post("/api/apps", json={"name": "app-b", "creds": {"telegram_token": "222:B"}})

    client.post("/api/webhooks", json={"channel": "telegram",
                                       "target_url": "http://127.0.0.1:9/tg-a", "app": "app-a"})
    client.post("/api/webhooks", json={"channel": "telegram",
                                       "target_url": "http://127.0.0.1:9/tg-b", "app": "app-b"})

    r = client.post("/telegram/client/sendMessage",
                    json={"chat_id": 1, "text": "for-a"},
                    headers={"X-MockPost-App": "app-a"})
    targets = [w["target_url"].split("/")[-1] for w in r.json()["webhooks_delivered"]]
    assert targets == ["tg-a"]

    md = client.get("/api/timeline/markdown", params={"app": "app-a"}).text
    assert "for-a" in md
    md_b = client.get("/api/timeline/markdown", params={"app": "app-b"}).text
    assert "for-a" not in md_b


def test_timeline_markdown(client):
    client.post("/telegram/bot1/sendMessage", json={"chat_id": 1, "text": "hello"})
    md = client.get("/api/timeline/markdown").text
    assert md.startswith("# MockPost — Timeline")
    assert "hello" in md
