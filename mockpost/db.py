"""SQLite connection (aiosqlite, WAL) and the full MockPost schema."""

from __future__ import annotations

import os

import aiosqlite

from mockpost.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    creds         TEXT NOT NULL,           -- JSON: credenciales por canal de la app
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id            TEXT PRIMARY KEY,
    test_id       TEXT,
    app_id        TEXT,
    channel       TEXT NOT NULL,
    direction     TEXT NOT NULL,
    sender        TEXT,
    recipient     TEXT,
    subject       TEXT,
    body          TEXT,
    raw_payload   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'received',
    created_at    TEXT NOT NULL,
    delivered_at  TEXT,
    read_at       TEXT,
    meta          TEXT                     -- JSON: per-channel extras (HTML body, attachments, headers)
);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_test_id ON messages(test_id);

CREATE TABLE IF NOT EXISTS webhook_events (
    id            TEXT PRIMARY KEY,
    test_id       TEXT,
    app_id        TEXT,
    channel       TEXT NOT NULL,
    target_url    TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    payload       TEXT NOT NULL,
    sent_at       TEXT,
    response_code INTEGER,
    response_body TEXT
);
CREATE INDEX IF NOT EXISTS idx_webhook_events_created ON webhook_events(sent_at);

CREATE TABLE IF NOT EXISTS webhooks_registry (
    id            TEXT PRIMARY KEY,
    app_id        TEXT,
    channel       TEXT NOT NULL,
    target_url    TEXT NOT NULL,
    token         TEXT,
    config        TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webpush_subscriptions (
    id                TEXT PRIMARY KEY,
    endpoint          TEXT NOT NULL,
    p256dh            TEXT NOT NULL,
    auth              TEXT NOT NULL,
    vapid_public_key  TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id            TEXT PRIMARY KEY,
    test_id       TEXT,
    channel       TEXT NOT NULL,
    identifier    TEXT NOT NULL,
    code          TEXT NOT NULL,
    purpose       TEXT,
    secret        TEXT,
    expires_at    TEXT,
    consumed_at   TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_otp_identifier ON otp_codes(identifier, created_at);

CREATE TABLE IF NOT EXISTS oauth_sessions (
    id                 TEXT PRIMARY KEY,
    provider           TEXT NOT NULL,
    client_id          TEXT NOT NULL,
    redirect_uri       TEXT NOT NULL,
    code               TEXT,
    access_token       TEXT,
    refresh_token      TEXT,
    fake_user_profile  TEXT NOT NULL,
    scope              TEXT,
    state              TEXT,
    created_at         TEXT NOT NULL,
    expires_at         TEXT
);

CREATE TABLE IF NOT EXISTS stripe_events (
    id            TEXT PRIMARY KEY,
    test_id       TEXT,
    event_type    TEXT NOT NULL,
    payload       TEXT NOT NULL,
    webhook_url   TEXT,
    signature     TEXT,
    sent_at       TEXT,
    response_code INTEGER,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stripe_events_created ON stripe_events(created_at);
"""

_conn: aiosqlite.Connection | None = None
_conn_path: str | None = None


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)


async def init_db() -> None:
    _ensure_dir(settings.db_path)
    global _conn, _conn_path
    # reopen if the path changed (tests use a DB per fixture; fixed in prod)
    if _conn is not None and _conn_path == settings.db_path:
        return
    if _conn is not None:
        await _conn.close()
        _conn = None
    _conn = await aiosqlite.connect(settings.db_path)
    _conn_path = settings.db_path
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA busy_timeout=5000")
    await _conn.executescript(SCHEMA)
    await _migrate(_conn)
    await _conn.commit()


async def _migrate(conn: aiosqlite.Connection) -> None:
    """Migraciones de esquemas antiguos (DB creadas antes de estas columnas)."""
    cur = await conn.execute("PRAGMA table_info(messages)")
    msg_cols = {r[1] for r in await cur.fetchall()}
    if "app_id" not in msg_cols:
        await conn.execute("ALTER TABLE messages ADD COLUMN app_id TEXT")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_app ON messages(app_id)")
    if "meta" not in msg_cols:
        await conn.execute("ALTER TABLE messages ADD COLUMN meta TEXT")
    cur = await conn.execute("PRAGMA table_info(webhooks_registry)")
    if "app_id" not in {r[1] for r in await cur.fetchall()}:
        await conn.execute("ALTER TABLE webhooks_registry ADD COLUMN app_id TEXT")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_webhooks_registry_app ON webhooks_registry(app_id)")
    cur = await conn.execute("PRAGMA table_info(webhook_events)")
    we_cols = {r[1] for r in await cur.fetchall()}
    if "app_id" not in we_cols:
        await conn.execute("ALTER TABLE webhook_events ADD COLUMN app_id TEXT")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_webhook_events_app ON webhook_events(app_id)")
    if "response_body" not in we_cols:
        await conn.execute("ALTER TABLE webhook_events ADD COLUMN response_body TEXT")


async def close_db() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


def get_db() -> aiosqlite.Connection:
    assert _conn is not None, "init_db() no llamado"
    return _conn
