"""Telegram Bot API fidelity: body formats, methods and error envelopes."""

from __future__ import annotations

import json

TOKEN = "123456789:AAHtest_token_that_is_thirty_five_x"


def messages(client):
    return client.get("/api/messages", params={"channel": "telegram"}).json()


def test_get_me_answers_like_the_real_api(client):
    r = client.post(f"/telegram/bot{TOKEN}/getMe")
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["id"] == 123456789
    assert result["is_bot"] is True
    assert result["username"]


def test_get_me_also_answers_on_get(client):
    assert client.get(f"/telegram/bot{TOKEN}/getMe").json()["ok"] is True


def test_send_message_accepts_form_urlencoded(client):
    r = client.post(f"/telegram/bot{TOKEN}/sendMessage",
                    data={"chat_id": "42", "text": "hola cámara", "parse_mode": "HTML"})
    assert r.status_code == 200
    assert r.json()["result"]["text"] == "hola cámara"
    assert messages(client)[0]["body"] == "hola cámara"


def test_send_message_accepts_multipart(client):
    r = client.post(f"/telegram/bot{TOKEN}/sendMessage",
                    files={"chat_id": (None, "42"), "text": (None, "multipart body")})
    assert r.json()["result"]["text"] == "multipart body"


def test_send_message_accepts_json_and_query_string(client):
    assert client.post(f"/telegram/bot{TOKEN}/sendMessage",
                       json={"chat_id": 42, "text": "json body"}).json()["ok"] is True
    assert client.get(f"/telegram/bot{TOKEN}/sendMessage",
                      params={"chat_id": 42, "text": "query body"}).json()["ok"] is True
    bodies = [m["body"] for m in messages(client)]
    assert "json body" in bodies and "query body" in bodies


def test_message_ids_are_unique_and_chat_type_is_derived(client):
    first = client.post(f"/telegram/bot{TOKEN}/sendMessage",
                        json={"chat_id": 42, "text": "one"}).json()["result"]
    second = client.post(f"/telegram/bot{TOKEN}/sendMessage",
                         json={"chat_id": -1001234, "text": "two"}).json()["result"]
    assert first["message_id"] != second["message_id"]
    assert first["chat"]["type"] == "private"
    assert second["chat"]["type"] == "supergroup"


def test_reply_markup_is_parsed_and_echoed(client):
    markup = {"inline_keyboard": [[{"text": "Open", "url": "https://example.test"}]]}
    r = client.post(f"/telegram/bot{TOKEN}/sendMessage",
                    data={"chat_id": "42", "text": "with markup",
                          "reply_markup": json.dumps(markup)})
    assert r.json()["result"]["reply_markup"] == markup


def test_missing_parameters_return_the_real_error_envelope(client):
    r = client.post(f"/telegram/bot{TOKEN}/sendMessage", json={"chat_id": 42})
    assert r.status_code == 400
    assert r.json() == {"ok": False, "error_code": 400,
                        "description": "Bad Request: message text is empty"}


def test_unknown_method_returns_404_envelope(client):
    r = client.post(f"/telegram/bot{TOKEN}/sendTelepathy", json={})
    assert r.status_code == 404
    assert r.json()["error_code"] == 404


def test_send_photo_and_document_return_message_objects(client):
    photo = client.post(f"/telegram/bot{TOKEN}/sendPhoto",
                        data={"chat_id": "42", "photo": "file_123", "caption": "a photo"})
    assert photo.json()["result"]["photo"][0]["file_id"] == "file_123"
    doc = client.post(f"/telegram/bot{TOKEN}/sendDocument",
                      data={"chat_id": "42", "document": "doc_9", "caption": "a doc"})
    assert doc.json()["result"]["document"]["file_id"] == "doc_9"


def test_edit_delete_and_chat_action(client):
    edited = client.post(f"/telegram/bot{TOKEN}/editMessageText",
                         json={"chat_id": 42, "message_id": 7, "text": "edited"})
    assert edited.json()["result"]["message_id"] == 7
    assert edited.json()["result"]["edit_date"]
    assert client.post(f"/telegram/bot{TOKEN}/deleteMessage",
                       json={"chat_id": 42, "message_id": 7}).json()["result"] is True
    assert client.post(f"/telegram/bot{TOKEN}/sendChatAction",
                       json={"chat_id": 42, "action": "typing"}).json()["result"] is True


def test_webhook_lifecycle(client):
    url = "http://127.0.0.1:9/webhooks/tg"
    assert client.post(f"/telegram/bot{TOKEN}/setWebhook", json={"url": url}).json()["result"] is True
    assert client.post(f"/telegram/bot{TOKEN}/getWebhookInfo").json()["result"]["url"] == url
    assert client.post(f"/telegram/bot{TOKEN}/deleteWebhook").json()["result"] is True
    assert client.post(f"/telegram/bot{TOKEN}/getWebhookInfo").json()["result"]["url"] == ""


def test_get_updates_returns_simulated_inbound_messages(client):
    client.post("/telegram/client/sendMessage", json={"chat_id": 555, "text": "from a user"})
    updates = client.post(f"/telegram/bot{TOKEN}/getUpdates").json()["result"]
    assert updates[0]["message"]["text"] == "from a user"
    assert updates[0]["message"]["chat"]["id"] == 555


def test_inbound_simulation_delivers_a_complete_update(client):
    """The delivered body must be a full Update: clients deserialize it with
    Update.de_json, which needs update_id, message_id, date, chat and from."""
    client.post("/api/apps", json={"name": "bot-app", "creds": {"bot_token": TOKEN}})
    client.post("/api/webhooks", json={"channel": "telegram", "app": "bot-app",
                                       "target_url": "http://127.0.0.1:9/tg"})
    client.post("/telegram/client/sendMessage",
                headers={"X-MockPost-App": "bot-app"},
                json={"chat_id": 778899, "text": "/start ABC12345", "from_user": "tester"})

    delivery = client.get("/api/webhooks/deliveries", params={"channel": "telegram"}).json()[0]
    update = json.loads(delivery["payload"])
    assert update["update_id"] >= 1
    message = update["message"]
    assert message["message_id"] and message["date"]
    assert message["chat"] == {"id": 778899, "type": "private"}
    assert message["from"]["username"] == "tester"
    assert message["text"] == "/start ABC12345"
