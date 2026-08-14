# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-08-14

### Fixed
- The inbound telegram simulation delivers a complete `Update` (`update_id`,
  `message_id`, `date`, `from` and a typed `chat`), so clients that parse it
  with `Update.de_json` no longer fail on the webhook they just received.

## [0.2.0] - 2026-08-13

### Added
- SMTP advertises AUTH PLAIN/LOGIN without TLS and accepts any credential, so
  clients that always log in (Flask-Mail, Nodemailer) need no changes.
- Telegram serves 13 Bot API methods, including `getMe`, on GET and POST, and
  reads JSON, form-urlencoded, multipart or query parameters.
- Web Push acts as a real push service: `/webpush/subscribe` returns a
  browser-shaped subscription and `/webpush/push/{id}` takes the aes128gcm
  body with its VAPID header, decrypts the payload and answers 201.
- Simulation of dead recipients: Web Push 410, FCM 404 UNREGISTERED and APNs
  410 Unregistered, with MCP tools for all three.
- MCP tools `create_push_subscription`, `list_push_subscriptions`,
  `expire_push_subscription` and `simulate_push_token_unregistered`.
- `MOCKPOST_STRICT_AUTH` enforces each channel's real authentication, plus
  `MOCKPOST_SMTP_USERNAME`/`MOCKPOST_SMTP_PASSWORD`.
- Captured messages carry a `meta` column with per-channel extras: HTML body
  and attachments, APNs headers, Slack blocks, Discord embeds.

### Changed
- WhatsApp accepts any Graph version in the path, returns `wamid.` ids and
  Graph error envelopes, and verifies webhooks over the real GET handshake.
- Twilio returns `SM`+32 hex SIDs with the full message resource, serves it
  over GET and posts StatusCallback as form-urlencoded to the request URL.
- APNs answers 200 with an empty body and the `apns-id` header; Discord
  answers 204 unless `wait=true`; Slack rejects empty payloads.
- Stripe objects use `cs_test_`/`pi_test_` ids and carry `created`,
  `client_secret`, `payment_status` and bracket-notation metadata.
- OAuth validates `redirect_uri`/`client_id`, supports the `refresh_token`
  grant, accepts JSON bodies and returns an `id_token` for `openid` scopes.

### Fixed
- Emails are parsed from bytes: 8bit UTF-8 bodies were captured with broken
  accents because the MIME was parsed from an already decoded string.
- Every recipient of a mail is captured, and each one gets its OTP row.
- `getWebhookInfo` reads the webhook registry instead of process memory, so a
  restart no longer reports the webhook as missing.

## [0.1.1] - 2026-08-13

### Added
- Registers the server in the MCP Registry: `server.json` migrated to the
  2025-12-11 schema and `mcp-name` marker added to the PyPI README.

## [0.1.0] - 2026-08-13

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
