"""Unified timeline: single source of ordering/format for HTML, Markdown and MCP."""

from __future__ import annotations

from dataclasses import dataclass

from mockpost.db import get_db

CHANNEL_ICONS = {
    "mail": "📧", "telegram": "💬", "whatsapp": "💬", "webpush": "🔔",
    "sms": "📱", "fcm": "🔔", "apns": "🍎", "slack": "🧵", "discord": "🎮",
    "stripe": "💳",
}


@dataclass
class TimelineEvent:
    timestamp: str
    channel: str
    icon: str
    direction: str
    sender: str | None
    recipient: str | None
    summary: str
    status: str
    message_id: str
    app: str | None = None


def _summary(channel: str, subject: str | None, body: str, raw: str) -> str:
    if subject:
        return subject
    text = body or raw
    return text[:80] + ("…" if len(text) > 80 else "")


async def _app_names() -> dict[str, str]:
    """app_id -> nombre."""
    from mockpost.apps import list_apps
    return {a["id"]: a["name"] for a in await list_apps()}


async def build_timeline(since: str | None = None, channels: list[str] | None = None,
                         test_id: str | None = None, limit: int = 200,
                         app_id: str | None = None) -> list[TimelineEvent]:
    db = get_db()
    events: list[TimelineEvent] = []
    ch_filter = tuple(channels) if channels else None
    names = await _app_names()

    def _and(ts_col: str = "created_at", extra: str = "", filter_ch: bool = True,
             filter_app: bool = True) -> tuple[str, list]:
        conds, params = [], []
        if since:
            conds.append(f"{ts_col} >= ?")
            params.append(since)
        if ch_filter and filter_ch:
            conds.append(f"channel IN ({','.join('?' * len(ch_filter))})")
            params.extend(ch_filter)
        if test_id:
            conds.append("test_id=?")
            params.append(test_id)
        if app_id and filter_app:
            conds.append("app_id=?")
            params.append(app_id)
        if extra:
            conds.append(extra)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        return where, params

    where, params = _and()
    cur = await db.execute(f"SELECT * FROM messages{where} ORDER BY created_at ASC LIMIT ?", [*params, limit])
    for r in await cur.fetchall():
        events.append(TimelineEvent(
            timestamp=r["created_at"], channel=r["channel"], icon=CHANNEL_ICONS.get(r["channel"], "📨"),
            direction=r["direction"], sender=r["sender"], recipient=r["recipient"],
            summary=_summary(r["channel"], r["subject"], r["body"], r["raw_payload"]),
            status=r["status"], message_id=r["id"], app=names.get(r["app_id"]),
        ))

    where2, params2 = _and(ts_col="sent_at", extra="sent_at IS NOT NULL" if since else "")
    cur = await db.execute(f"SELECT * FROM webhook_events{where2} ORDER BY sent_at ASC LIMIT ?", [*params2, limit])
    for r in await cur.fetchall():
        events.append(TimelineEvent(
            timestamp=r["sent_at"], channel=r["channel"], icon=CHANNEL_ICONS.get(r["channel"], "🔁"),
            direction="webhook", sender="mockpost", recipient=r["target_url"],
            summary=f"{r['event_type']} → {r['response_code']}", status=str(r["response_code"]),
            message_id=r["id"], app=names.get(r["app_id"]),
        ))

    # stripe_events has no 'channel' or 'app_id' column: only queried when the
    # channel filter includes it (or there is no filter) and without app filtering
    if (not ch_filter or "stripe" in ch_filter) and not app_id:
        where3, params3 = _and(filter_ch=False, filter_app=False)
        cur = await db.execute(f"SELECT * FROM stripe_events{where3} ORDER BY created_at ASC LIMIT ?", [*params3, limit])
        for r in await cur.fetchall():
            events.append(TimelineEvent(
                timestamp=r["created_at"], channel="stripe", icon="💳",
                direction="webhook", sender="stripe", recipient=r["webhook_url"],
                summary=r["event_type"], status=str(r["response_code"] or ""),
                message_id=r["id"],
            ))

    events.sort(key=lambda e: e.timestamp)
    return events[:limit]


def timeline_markdown(events: list[TimelineEvent]) -> str:
    lines = ["# MockPost — Timeline", "", "| Time | Channel | Direction | From → To | Summary | Status |",
             "|---|---|---|---|---|---|"]
    for e in events:
        ts = e.timestamp[11:19] if len(e.timestamp) >= 19 else e.timestamp
        app_tag = f" [{e.app}]" if e.app else ""
        lines.append(f"| {ts} | {e.icon} {e.channel}{app_tag} | {e.direction} | {e.sender or ''} → {e.recipient or ''} | "
                     f"{e.summary.replace('|', '/')} | {e.status} |")
    return "\n".join(lines)
