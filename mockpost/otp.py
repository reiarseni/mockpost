"""OTP: code insertion, latest-code lookup, and TOTP (pyotp)."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone

import pyotp

from mockpost.config import utcnow
from mockpost.db import get_db


async def get_latest_otp(identifier: str, channel: str = "any", test_id: str | None = None) -> dict | None:
    db = get_db()
    where = ["identifier=?", "consumed_at IS NULL"]
    params: list = [identifier]
    if channel != "any":
        where.append("channel=?")
        params.append(channel)
    if test_id:
        where.append("test_id=?")
        params.append(test_id)
    q = "SELECT * FROM otp_codes WHERE " + " AND ".join(where) + " ORDER BY created_at DESC LIMIT 1"
    cur = await db.execute(q, params)
    row = await cur.fetchone()
    return dict(row) if row else None


async def generate_totp_secret(identifier: str) -> dict:
    db = get_db()
    secret = pyotp.random_base32()
    otpauth = pyotp.totp.TOTP(secret).provisioning_uri(identifier, issuer_name="MockPost")
    await db.execute(
        "INSERT INTO otp_codes (id, channel, identifier, code, secret, created_at) VALUES (?, 'totp', ?, '', ?, ?)",
        (str(uuid.uuid4()), identifier, secret, utcnow()),
    )
    await db.commit()
    return {"identifier": identifier, "secret": secret, "otpauth_url": otpauth}


async def get_totp_code(identifier: str) -> dict | None:
    """Current TOTP code with a ±1 window (tolerates the 30s rotation mid-verification)."""
    db = get_db()
    cur = await db.execute(
        "SELECT * FROM otp_codes WHERE channel='totp' AND identifier=? ORDER BY created_at DESC LIMIT 1",
        (identifier,),
    )
    row = await cur.fetchone()
    if not row or not row["secret"]:
        return None
    totp = pyotp.TOTP(row["secret"])
    now = datetime.now(timezone.utc)
    valid_windows = [now - timedelta(seconds=30), now, now + timedelta(seconds=30)]
    codes = {totp.at(ts) for ts in valid_windows}
    return {"identifier": identifier, "code": totp.now(), "valid_codes": sorted(codes),
            "period": 30, "secret": row["secret"]}


async def consume_otp(identifier: str, code: str) -> bool:
    """Consume the latest unused OTP matching the code (login-style verification)."""
    db = get_db()
    cur = await db.execute(
        "SELECT * FROM otp_codes WHERE identifier=? AND channel IN ('sms','mail') AND consumed_at IS NULL "
        "ORDER BY created_at DESC LIMIT 5",
        (identifier,),
    )
    rows = await cur.fetchall()
    for row in rows:
        if row["code"] == code:
            await db.execute("UPDATE otp_codes SET consumed_at=? WHERE id=?", (utcnow(), row["id"]))
            await db.commit()
            return True
    return False
