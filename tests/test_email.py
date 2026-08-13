"""SMTP fidelity: AUTH, charset, multipart, several recipients."""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage

from mockpost.config import settings
from mockpost.smtp_server import authenticator, decode_subject, extract_bodies


def _message(subject: str, to: str | list[str], text: str, html: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "app@test.com"
    msg["To"] = to if isinstance(to, str) else ", ".join(to)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def test_auth_is_advertised_and_accepts_any_credential(client):
    with smtplib.SMTP("localhost", client.smtp_port) as s:
        s.ehlo()
        assert s.has_extn("auth")
        s.login("whatever", "whatever")
        s.send_message(_message("Logged in", "user@test.com", "body"))

    msgs = client.get("/api/messages", params={"channel": "mail"}).json()
    assert msgs[0]["subject"] == "Logged in"


def test_utf8_body_and_subject_survive_capture(client):
    with smtplib.SMTP("localhost", client.smtp_port) as s:
        s.send_message(_message("Acción requerida", "user@test.com",
                                "La cámara grabó a Ramón: ñ, é, ü"))

    msg = client.get("/api/messages", params={"channel": "mail"}).json()[0]
    assert msg["subject"] == "Acción requerida"
    assert "La cámara grabó a Ramón: ñ, é, ü" in msg["body"]


def test_html_alternative_and_attachment_land_in_meta(client):
    msg = _message("Report", "user@test.com", "plain version", html="<b>rich version</b>")
    msg.add_attachment(b"col1,col2\n1,2\n", maintype="text", subtype="csv", filename="report.csv")
    with smtplib.SMTP("localhost", client.smtp_port) as s:
        s.send_message(msg)

    captured = client.get("/api/messages", params={"channel": "mail"}).json()[0]
    meta = json.loads(captured["meta"])
    assert captured["body"].strip() == "plain version"
    assert "<b>rich version</b>" in meta["html"]
    assert meta["attachments"] == ["report.csv"]


def test_every_recipient_is_captured_and_gets_the_otp(client):
    with smtplib.SMTP("localhost", client.smtp_port) as s:
        s.send_message(_message("Code", ["a@test.com", "b@test.com"], "Your code is 998877"))

    captured = client.get("/api/messages", params={"channel": "mail"}).json()[0]
    assert captured["recipient"] == "a@test.com, b@test.com"
    assert json.loads(captured["meta"])["recipients"] == ["a@test.com", "b@test.com"]

    for identifier in ("a@test.com", "b@test.com"):
        otp = client.get("/api/otp/latest", params={"identifier": identifier}).json()
        assert otp["code"] == "998877"


def test_decode_subject_handles_rfc2047_and_plain_text():
    assert decode_subject("=?utf-8?B?QWNjacOzbg==?=") == "Acción"
    assert decode_subject("Plain subject") == "Plain subject"
    assert decode_subject("") == ""


def test_extract_bodies_prefers_the_first_part_of_each_type():
    msg = _message("s", "user@test.com", "the text", html="<p>the html</p>")
    text, html = extract_bodies(msg)
    assert text.strip() == "the text"
    assert "the html" in html


def test_authenticator_enforces_configured_credentials():
    settings.smtp_username, settings.smtp_password = "user", "pass"
    try:
        from aiosmtpd.smtp import LoginPassword
        good = authenticator(None, None, None, "LOGIN", LoginPassword(b"user", b"pass"))
        bad = authenticator(None, None, None, "LOGIN", LoginPassword(b"user", b"nope"))
        assert good.success is True
        assert bad.success is False
    finally:
        settings.smtp_username, settings.smtp_password = "", ""
