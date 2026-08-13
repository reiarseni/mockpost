"""Unauthenticated SMTP server (MailHog-style) that captures full MIME.

One port per app: the SMTP port identifies the app (MOCKPOST_APPS='app-a:1025,...').
The default port (settings.smtp_port) captures without an app (global queue).
"""

from __future__ import annotations

import asyncio
import email
from email.message import Message

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP

from mockpost.apps import get_app_by_name, upsert_app
from mockpost.config import settings
from mockpost.store import insert_message


class CaptureHandler:
    def __init__(self, app_id: str | None = None):
        self.app_id = app_id

    async def handle_DATA(self, server: SMTP, session, envelope):
        raw = envelope.content.decode("utf-8", errors="replace")
        msg: Message = email.message_from_string(raw)
        subject = str(msg.get("Subject", "") or "")
        sender = envelope.mail_from
        recipient = envelope.rcpt_tos[0] if envelope.rcpt_tos else None

        # Plain body: try text/plain first, fall back to the full text
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
        if not body:
            body = raw

        await insert_message(
            "mail", "outbound", body,
            sender=sender, recipient=recipient, subject=subject,
            raw_payload=raw, status="received",
            app_id=self.app_id,
        )
        return "250 Message accepted for delivery"


_controllers: list[Controller] = []


async def start_smtp() -> None:
    if _controllers:
        return
    loop = asyncio.get_running_loop()

    def _run(port: int, app_id: str | None) -> None:
        handler = CaptureHandler(app_id)
        # localhost by default: no auth SMTP must not be reachable from the LAN
        controller = Controller(handler, hostname=settings.smtp_host, port=port)
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
