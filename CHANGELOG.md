# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release of MockPost, a local multi-channel message emulator.
- Channels: SMTP email (no auth, MailHog-style), Telegram Bot API
  (`sendMessage`/`getUpdates`/`sendPhoto`/`setWebhook`), WhatsApp Cloud API,
  Web Push with real VAPID validation, Twilio SMS (`Messages.json` +
  `StatusCallback`), FCM, APNs, Slack and Discord incoming webhooks,
  Stripe (`checkout/sessions`, `payment_intents`, signed `Stripe-Signature`
  events), OTP (SMS/email/TOTP), fake OAuth2 for Google/GitHub/Facebook/X,
  signed social webhooks (GitHub, Facebook, X) and Google tokeninfo/revoke.
- Unified web timeline (`/`) with per-channel tabs, message detail, filters,
  per-app isolation and a "Copy as Markdown" button.
- Internal API (`/api/*`) consumed by the panel and the MCP server.
- MCP server (`mockpost-mcp`, stdio) with 27 tools for inspection,
  simulation, OTP, OAuth and timeline verification.

### Security
- Bind HTTP and SMTP to `127.0.0.1` by default (`MOCKPOST_HOST`,
  `MOCKPOST_SMTP_HOST`); `docker-compose.yml` publishes on loopback only.
- Webhook `target_url` validation: http(s) only, blocks link-local /
  metadata-cloud addresses (`169.254.0.0/16`, `100.100.100.200`), no
  redirects followed, optional `MOCKPOST_ALLOWED_WEBHOOK_HOSTS` allowlist.
- Per-app isolation: apps identified by their fake credentials (bot token,
  Twilio SID, Stripe key, phone_id, FCM project, SMTP port).
- Webhook delivery history (`list_webhook_deliveries`) including the app's
  response body even when the app was down.
- Docker images (`Dockerfile`, `Dockerfile.mcp`) and `docker-compose.yml`.
- PyPI packaging with `mockpost` and `mockpost-mcp` console scripts.
- GitHub Actions CI: test matrix (3.10/3.12/3.13), build, publish.
- MCP Registry metadata (`server.json`).
