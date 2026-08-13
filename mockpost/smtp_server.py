"""SMTP server (MailHog-style) that captures full MIME, with SMTP AUTH.

One port per app: the SMTP port identifies the app (MOCKPOST_APPS='app-a:1025,...').
The default port (settings.smtp_port) captures without an app (global queue).

AUTH (RFC 4954) is advertised without TLS and accepts any credential, so
clients that always log in (Flask-Mail, Nodemailer, Laravel Mailer) work
without changes. With MOCKPOST_STRICT_AUTH the session must authenticate,
and if MOCKPOST_SMTP_USERNAME/PASSWORD are set the pair must match.
"""

from __future__ import annotations

import asyncio
import email
from email.header import decode_header, make_header
from email.message import Message

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, AuthResult, LoginPassword

from mockpost.apps import get_app_by_name, upsert_app
from mockpost.config import settings
from mockpost.store import insert_message


def decode_subject(raw_subject: str) -> str:
    """Decode an RFC 2047 header ('=?utf-8?B?...?=') into readable text."""
    if not raw_subject:
        return ""
    try:
        return str(make_header(decode_header(raw_subject)))
    except Exception:
        return raw_subject


def extract_bodies(msg: Message) -> tuple[str, str]:
    """Return (text, html) decoded with each part's charset."""
    text, html = "", ""
    for part in msg.walk():
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        decoded = payload.decode(charset, errors="replace")
        ctype = part.get_content_type()
        if ctype == "text/plain" and not text:
            text = decoded
        elif ctype == "text/html" and not html:
            html = decoded
    return text, html


def attachment_names(msg: Message) -> list[str]:
    return [name for part in msg.walk() if (name := part.get_filename())]


def authenticator(server, session, envelope, mechanism, auth_data):
    """Accept any credential, or the configured pair under strict auth."""
    if isinstance(auth_data, LoginPassword):
        username = auth_data.login.decode(errors="replace")
        password = auth_data.password.decode(errors="replace")
    else:
        username, password = str(auth_data or ""), ""
    expected_user = settings.smtp_username
    expected_password = settings.smtp_password
    if expected_user or expected_password:
        if username != expected_user or password != expected_password:
            return AuthResult(success=False, handled=False)
    return AuthResult(success=True, handled=True, auth_data=username)


class CaptureHandler:
    def __init__(self, app_id: str | None = None):
        self.app_id = app_id

    async def handle_DATA(self, server: SMTP, session, envelope):
        # Parsed from BYTES, never from a decoded string: with
        # Content-Transfer-Encoding 8bit, get_payload(decode=True) on a
        # message built from str re-encodes it as ASCII and destroys UTF-8.
        msg: Message = email.message_from_bytes(envelope.content)
        raw = envelope.content.decode("utf-8", errors="replace")

        subject = decode_subject(str(msg.get("Subject", "") or ""))
        text, html = extract_bodies(msg)
        # All recipients, like a real MTA: the envelope may carry several
        # (To/Cc/Bcc all land in RCPT TO).
        recipients = ", ".join(envelope.rcpt_tos) if envelope.rcpt_tos else None

        await insert_message(
            "mail", "outbound", text or html or raw,
            sender=envelope.mail_from, recipient=recipients, subject=subject,
            raw_payload=raw, status="received",
            app_id=self.app_id,
            meta={
                "html": html or None,
                "text": text or None,
                "recipients": envelope.rcpt_tos,
                "attachments": attachment_names(msg),
            },
        )
        return "250 Message accepted for delivery"


_controllers: list[Controller] = []


async def start_smtp() -> None:
    if _controllers:
        return
    loop = asyncio.get_running_loop()

    def _run(port: int, app_id: str | None) -> None:
        handler = CaptureHandler(app_id)
        # localhost by default: an SMTP that accepts any credential must not
        # be reachable from the LAN.
        controller = Controller(
            handler, hostname=settings.smtp_host, port=port,
            authenticator=authenticator,
            auth_require_tls=False,
            auth_required=settings.strict_auth,
        )
        controller.start()
        _controllers.append(controller)

    # Default global port
    loop.run_in_executor(None, _run, settings.smtp_port, None)
    # One port per app registered in MOCKPOST_APPS
    for app_name, port in settings.smtp_apps.items():
        # Make sure the app exists (the SMTP port identifies it)
        await upsert_app(app_name, {"smtp_port": str(port)})
        app = await get_app_by_name(app_name)
        loop.run_in_executor(None, _run, port, app["id"] if app else None)


async def stop_smtp() -> None:
    for c in _controllers:
        c.stop()
    _controllers.clear()
