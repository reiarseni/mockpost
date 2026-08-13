# Security Policy

MockPost is a **local testing tool**. It intentionally runs with no
authentication because it only ever handles simulated messages and locally
generated secrets — never real credentials, real sends or production data.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

## Reporting a vulnerability

If you find a security issue (e.g. a way to make MockPost reach a real
service, leak a locally generated secret, or execute code on the host),
please **do not open a public issue**. Report it privately to
`reiarseni@gmail.com` with:

- A description of the vulnerability
- Steps to reproduce
- Impact assessment

You will receive an acknowledgment within 48 hours and a fix plan shortly
after. Do not disclose the issue publicly until a fix is released.

## Known posture (by design)

- **No auth** on the panel or API. MockPost binds to **localhost by default**
  (HTTP via `MOCKPOST_HOST`, SMTP via `MOCKPOST_SMTP_HOST`, and
  `docker-compose.yml` publishes on `127.0.0.1` only). If you must expose it
  on a network, put it behind a firewall/VPN and set `MOCKPOST_HOST`
  explicitly — without auth, any network exposure lets others read the
  captured messages (including OTP codes) and fire webhooks.
- **Webhook SSRF guards**: `target_url` must be `http(s)`, hosts resolving
  to link-local/metadata-cloud addresses (`169.254.0.0/16`,
  `100.100.100.200`) are rejected, redirects are not followed, and
  `MOCKPOST_ALLOWED_WEBHOOK_HOSTS` (comma-separated) restricts delivery to
  an explicit host allowlist when set.
- **Generated secrets** (`whsec_...`, VAPID keys, OAuth JWT key) are random
  per process and overrideable via env vars — they are never real.
- **SQLite** stores only simulated data; the DB file lives in `./data/`
  (gitignored).
