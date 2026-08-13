"""Internal API /api/config: effective per-channel values (host, ports, tokens, secrets)."""

from __future__ import annotations

from fastapi import APIRouter

from mockpost.config import settings
from mockpost.signing import vapid_public_key_b64

router = APIRouter(prefix="/api/config", tags=["api"])

CHANNELS = ("mail", "telegram", "whatsapp", "webpush", "sms", "fcm", "apns", "slack", "discord", "stripe", "oauth")


def _config() -> dict:
    base = settings.mockpost_url
    return {
        "apps": {"smtp_ports": settings.smtp_apps,
                 "note": "Register apps with their fake credentials in /api/apps; "
                         "MockPost identifies each app by those credentials (no extra headers)."},
        "mail": {"protocol": "SMTP", "host": "localhost", "port": settings.smtp_port,
                 "auth": "required" if settings.strict_auth else "any",
                 "auth_mechanisms": ["PLAIN", "LOGIN"], "starttls": False,
                 "username": settings.smtp_username or "<any>",
                 "password": settings.smtp_password or "<any>",
                 "env": "SMTP_HOST=localhost", "env_port": f"SMTP_PORT={settings.smtp_port}",
                 "note": "AUTH is advertised without TLS and any credential is accepted, so "
                         "clients that always log in (Flask-Mail, Nodemailer) need no changes."},
        "telegram": {"base_url": f"{base}/telegram", "env": "TELEGRAM_API_BASE_URL=<base_url>",
                     "note": "Put the bot token in the URL: /telegram/bot<TOKEN>/..."},
        "whatsapp": {"base_url": f"{base}/whatsapp/v1", "env": "WHATSAPP_GRAPH_BASE_URL=<base_url>"},
        "webpush": {"endpoint": f"{base}/webpush/send", "subscribe": f"{base}/webpush/subscribe",
                    "vapid_public_key": vapid_public_key_b64(), "vapid_contact": settings.vapid_contact},
        "sms": {"base_url": f"{base}/twilio/2010-04-01/Accounts/AC00000000000000000000000000000000",
                "env": "TWILIO_BASE_URL=<base_url>", "note": "account_sid and auth_token accept any value"},
        "fcm": {"endpoint": f"{base}/fcm/v1/projects/{{project_id}}/messages:send",
                "env": "FCM_ENDPOINT=<endpoint>", "note": "Bearer token not validated (shape only)"},
        "apns": {"endpoint": f"{base}/apns/3/device/{{device_token}}",
                 "env": "APNS_ENDPOINT=<endpoint>"},
        "slack": {"webhook_pattern": f"{base}/slack/webhook/{{webhook_id}}",
                  "env": "SLACK_WEBHOOK_URL=<url with your webhook_id>"},
        "discord": {"webhook_pattern": f"{base}/discord/webhook/{{webhook_id}}",
                    "env": "DISCORD_WEBHOOK_URL=<url with your webhook_id>"},
        "stripe": {"api_base": f"{base}/stripe/v1", "webhook_secret": settings.stripe_webhook_secret,
                   "env": "STRIPE_API_BASE=<api_base>", "env_secret": f"STRIPE_WEBHOOK_SECRET={settings.stripe_webhook_secret}"},
        "oauth": {"google": {"authorize": f"{base}/oauth/google/authorize", "token": f"{base}/oauth/google/token",
                             "userinfo": f"{base}/oauth/google/userinfo",
                             "tokeninfo": f"{base}/oauth/google/tokeninfo", "revoke": f"{base}/oauth/google/revoke"},
                  "github": {"authorize": f"{base}/oauth/github/authorize", "token": f"{base}/oauth/github/token",
                             "userinfo": f"{base}/oauth/github/user",
                             "webhook": f"{base}/github/repos/{{owner}}/{{repo}}/hooks", "simulate": f"{base}/github/simulate"},
                  "facebook": {"authorize": f"{base}/oauth/facebook/authorize", "token": f"{base}/oauth/facebook/token",
                               "userinfo": f"{base}/oauth/facebook/me",
                               "webhook_verify": f"{base}/facebook/webhook?hub.mode=subscribe&hub.verify_token=<token>",
                               "simulate": f"{base}/facebook/simulate"},
                  "x": {"authorize": f"{base}/oauth/x/authorize", "token": f"{base}/oauth/x/token",
                        "userinfo": f"{base}/oauth/x/2/users/me",
                        "webhook": f"{base}/x/webhook", "crc": f"{base}/x/webhook/crc", "simulate": f"{base}/x/simulate"},
                  "note": "client_id/secret accept any value; JWT signed with a local key; "
                          "social webhooks signed with a per-app secret (X-Hub-Signature-256 / X-Twitter-Webhooks-Signature)"},
        "github": {"webhook": f"{base}/github/repos/{{owner}}/{{repo}}/hooks",
                   "simulate": f"{base}/github/simulate",
                   "note": "X-GitHub-Event + X-Hub-Signature-256 (HMAC-SHA256 with the app secret)"},
        "facebook": {"webhook_verify": f"{base}/facebook/webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<ch>",
                     "simulate": f"{base}/facebook/simulate",
                     "note": "hub.* verification + X-Hub-Signature-256 (HMAC-SHA256 with app secret)"},
        "x": {"webhook": f"{base}/x/webhook", "crc": f"{base}/x/webhook/crc",
              "simulate": f"{base}/x/simulate",
              "note": "CRC check (crc_token -> response_token) + X-Twitter-Webhooks-Signature (base64 HMAC-SHA256)"},
    }


@router.get("")
async def get_config():
    return _config()


@router.get("/{channel}")
async def get_channel_config(channel: str):
    conf = _config()
    if channel in conf:
        return conf[channel]
    if channel == "oauth":
        return conf["oauth"]
    return {"error": "unknown_channel", "channel": channel}
