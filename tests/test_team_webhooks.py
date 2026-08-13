"""Slack and Discord incoming webhooks: real status codes and payload shapes."""

from __future__ import annotations

import json

SLACK = "/slack/webhook/T000/B000/XXXX"
DISCORD = "/discord/webhook/123456789"


def test_slack_answers_the_literal_ok(client):
    r = client.post("/slack/webhook/T000", json={"text": "deploy finished"})
    assert r.status_code == 200
    assert r.text == "ok"
    assert client.get("/api/messages", params={"channel": "slack"}).json()[0]["body"] == \
        "deploy finished"


def test_slack_blocks_are_summarized(client):
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "*Build 42* passed"}},
              {"type": "section", "fields": [{"type": "mrkdwn", "text": "Duration: 3m"}]}]
    r = client.post("/slack/webhook/T000", json={"blocks": blocks})
    assert r.text == "ok"
    msg = client.get("/api/messages", params={"channel": "slack"}).json()[0]
    assert msg["body"] == "*Build 42* passed | Duration: 3m"
    assert json.loads(msg["meta"])["blocks"] == blocks


def test_slack_rejects_an_empty_payload(client):
    r = client.post("/slack/webhook/T000", json={"username": "bot"})
    assert r.status_code == 400
    assert r.text == "invalid_payload"


def test_slack_accepts_the_form_payload_field(client):
    r = client.post("/slack/webhook/T000", data={"payload": json.dumps({"text": "from form"})})
    assert r.text == "ok"
    assert client.get("/api/messages", params={"channel": "slack"}).json()[0]["body"] == "from form"


def test_discord_answers_204_without_a_body(client):
    r = client.post(DISCORD, json={"content": "release shipped"})
    assert r.status_code == 204
    assert r.content == b""
    assert client.get("/api/messages", params={"channel": "discord"}).json()[0]["body"] == \
        "release shipped"


def test_discord_wait_true_returns_the_message_object(client):
    r = client.post(DISCORD, params={"wait": "true"}, json={"content": "with wait"})
    assert r.status_code == 200
    assert r.json()["content"] == "with wait"
    assert r.json()["webhook_id"] == "123456789"


def test_discord_embeds_are_summarized(client):
    embeds = [{"title": "Deploy", "description": "v1.2.3 to production"}]
    r = client.post(DISCORD, json={"embeds": embeds})
    assert r.status_code == 204
    msg = client.get("/api/messages", params={"channel": "discord"}).json()[0]
    assert msg["body"] == "Deploy v1.2.3 to production"
    assert json.loads(msg["meta"])["embeds"] == embeds


def test_discord_rejects_an_empty_message(client):
    r = client.post(DISCORD, json={"username": "bot"})
    assert r.status_code == 400
    assert r.json()["code"] == 50006
