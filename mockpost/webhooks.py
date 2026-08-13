"""Webhook event delivery to the registered app.

Per-app isolation: an event is delivered ONLY to webhooks of the same app
(never to another app's or to global ones). Every call is recorded in
webhook_events with the response code and body returned by the app, so an
LLM can inspect it via MCP even when the app was down.

Security (SSRF): `target_url` accepts http(s) only and never cloud-metadata /
link-local addresses (169.254.x.x). If `MOCKPOST_ALLOWED_WEBHOOK_HOSTS`
(comma-separated) is set, delivery is restricted to those hosts — the app
under test usually lives on localhost/LAN.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx

from mockpost.config import utcnow
from mockpost.db import get_db

TIMEOUT = 5.0

# Cloud-metadata and link-local addresses: they must never receive webhooks.
# NOTE: loopback (127.0.0.1) is allowed on purpose — the app under test runs
# on the same machine; metadata SSRF is what gets blocked.
_BLOCKED_NETS = (
    ipaddress.ip_network("169.254.0.0/16"),   # link-local (incl. AWS/GCP/Azure metadata)
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba metadata
)


def _validate_webhook_url(target_url: str) -> None:
    """Reject non-http(s) URLs and metadata/link-local hosts."""
    parsed = urlparse(target_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"target_url must be http(s): {target_url}")

    allowed_hosts = os.environ.get("MOCKPOST_ALLOWED_WEBHOOK_HOSTS", "")
    if allowed_hosts:
        allowed = {h.strip().lower() for h in allowed_hosts.split(",") if h.strip()}
        if parsed.hostname.lower() not in allowed:
            raise ValueError(f"host {parsed.hostname} not in MOCKPOST_ALLOWED_WEBHOOK_HOSTS")

    # resolve the host and block dangerous IPs
    try:
        ips = {ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(parsed.hostname, None)}
    except OSError:
        return  # unknown host: delivery will fail with a network error anyway
    for ip in ips:
        if ip.version == 4 and any(ip in net for net in _BLOCKED_NETS):
            raise ValueError(f"host {parsed.hostname} resolves to blocked address {ip}")


async def deliver_webhook(
    channel: str,
    target_url: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    test_id: str | None = None,
    app_id: str | None = None,
    form: bool = False,
) -> dict:
    """POST the event to target_url and record the result in webhook_events
    (response code + body returned by the app, or an error if it was down).

    `form` sends the payload as x-www-form-urlencoded instead of JSON, which is
    how Twilio posts its StatusCallback."""
    db = get_db()
    event_id = str(uuid.uuid4())
    response_code = None
    response_body = None
    try:
        _validate_webhook_url(target_url)
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            if form:
                resp = await client.post(target_url, data=payload, headers=headers or {})
            else:
                resp = await client.post(target_url, json=payload, headers=headers or {})
            response_code = resp.status_code
            response_body = resp.text[:2000]
    except (httpx.HTTPError, ValueError) as exc:
        response_code = 0  # unreachable / network error / blocked URL
        response_body = f"error: {exc.__class__.__name__}: {exc}"[:2000]
    await db.execute(
        "INSERT INTO webhook_events (id, test_id, app_id, channel, target_url, event_type, payload, sent_at, response_code, response_body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, test_id, app_id, channel, target_url, event_type,
         json.dumps(payload, ensure_ascii=False), utcnow(), response_code, response_body),
    )
    await db.commit()
    return {"event_id": event_id, "target_url": target_url, "response_code": response_code,
            "response_body": response_body}


async def deliver_to_app_webhooks(
    channel: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    test_id: str | None = None,
    app_id: str | None = None,
) -> list[dict]:
    """Deliver the event to the webhooks of the given app (that app only).

    Without app_id, the event is delivered to nobody: it stays on the
    timeline as a simulation without a send, since there is no identified
    app that should receive it."""
    if not app_id:
        return []
    db = get_db()
    cur = await db.execute("SELECT * FROM webhooks_registry WHERE channel=? AND app_id=?",
                           (channel, app_id))
    rows = await cur.fetchall()
    results = []
    for row in rows:
        results.append(await deliver_webhook(channel, row["target_url"], event_type, payload,
                                             headers=headers, test_id=test_id, app_id=app_id))
    return results


async def list_webhook_deliveries(*, app_id: str | None = None, channel: str | None = None,
                                  test_id: str | None = None, limit: int = 50) -> list[dict]:
    db = get_db()
    where: list[str] = []
    params: list[Any] = []
    if app_id:
        where.append("app_id=?")
        params.append(app_id)
    if channel:
        where.append("channel=?")
        params.append(channel)
    if test_id:
        where.append("test_id=?")
        params.append(test_id)
    q = "SELECT * FROM webhook_events"
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY sent_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(q, params)
    return [dict(r) for r in await cur.fetchall()]
