"""MockPost configuration: env vars with defaults generated at startup.

Secrets are generated once per process and stay reachable via the
internal /api/config API and the get_channel_config MCP tool.
"""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_secret(prefix: str = "") -> str:
    return prefix + secrets.token_hex(16)


def _generate_vapid_keys() -> dict:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    key = ec.generate_private_key(ec.SECP256R1())
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_der = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {
        "private_pem": priv_pem.decode(),
        "public_b64": base64.urlsafe_b64encode(pub_der).rstrip(b"=").decode(),
    }


@dataclass
class Settings:
    http_port: int = 8090
    smtp_port: int = 1025
    smtp_host: str = "127.0.0.1"
    db_path: str = "./data/mockpost.db"
    mockpost_url: str = "http://localhost:8090"
    # App -> SMTP port map, format "app-a:1025,app-b:1026"
    smtp_apps: dict = field(default_factory=dict)

    stripe_webhook_secret: str = field(default_factory=lambda: _random_secret("whsec_"))
    vapid_contact: str = "mailto:mockpost@test.local"
    vapid_keys: dict = field(default_factory=_generate_vapid_keys)
    oauth_jwt_key: str = field(default_factory=lambda: _random_secret())
    oauth_token_ttl_minutes: int = 60
    oauth_refresh_ttl_minutes: int = 60 * 24 * 7

    default_oauth_profile: dict = field(default_factory=lambda: {
        "google": {"sub": "fake-google-user-1", "email": "user@test.com", "email_verified": True, "name": "Fake User", "picture": "https://example.com/avatar.png"},
        "github": {"id": 424242, "login": "fakeuser", "name": "Fake User", "email": "user@test.com", "avatar_url": "https://example.com/avatar.png"},
        "facebook": {"id": "10234567890123456", "name": "Fake User", "email": "user@test.com", "picture": {"data": {"url": "https://example.com/avatar.png"}}},
        "x": {"id": "1234567890", "name": "Fake User", "username": "fakeuser", "email": "user@test.com", "profile_image_url": "https://example.com/avatar.png"},
    })

    # Per-app webhook secrets: app name -> {github, facebook, x}
    # Generated randomly on first use if the app does not define its own.
    social_webhook_secrets: dict = field(default_factory=dict)
    # Revoked OAuth JWTs (Google revoke): stateless, kept in-process.
    revoked_oauth_tokens: set = field(default_factory=set)

    def __post_init__(self) -> None:
        self.http_port = int(os.environ.get("MOCKPOST_HTTP_PORT", self.http_port))
        self.smtp_port = int(os.environ.get("MOCKPOST_SMTP_PORT", self.smtp_port))
        self.smtp_host = os.environ.get("MOCKPOST_SMTP_HOST", self.smtp_host)
        self.db_path = os.environ.get("MOCKPOST_DB_PATH", self.db_path)
        self.mockpost_url = os.environ.get("MOCKPOST_URL", self.mockpost_url)
        self.stripe_webhook_secret = os.environ.get("MOCKPOST_STRIPE_WEBHOOK_SECRET", self.stripe_webhook_secret)
        self.vapid_contact = os.environ.get("MOCKPOST_VAPID_CONTACT", self.vapid_contact)
        self.oauth_jwt_key = os.environ.get("MOCKPOST_OAUTH_JWT_KEY", self.oauth_jwt_key)
        apps = os.environ.get("MOCKPOST_APPS", "")
        for item in apps.split(","):
            if ":" in item:
                name, port = item.rsplit(":", 1)
                if name and port.isdigit():
                    self.smtp_apps[name.strip()] = int(port)


settings = Settings()


def utcnow() -> str:
    return _now()


def expire_at(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
