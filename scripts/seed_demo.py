"""Seed MockPost with a realistic multi-channel demo timeline.

Usage: MOCKPOST_URL=http://localhost:8090 uv run python scripts/seed_demo.py
"""

from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("MOCKPOST_URL", "http://localhost:8090")
CLIENT = httpx.Client(timeout=10)


def post(path: str, json: dict, headers: dict | None = None):
    r = CLIENT.post(f"{BASE}{path}", json=json, headers=headers or {})
    r.raise_for_status()
    return r.json()


def main() -> None:
    # App A: e-commerce
    a = post("/api/apps", {"name": "shop-app", "creds": {
        "telegram_token": "123456:SHOP_TOKEN",
        "twilio_sid": "ACshopdemo",
        "stripe_key": "sk_test_shopdemo",
        "whatsapp_phone_id": "1001001001",
    }})

    # App B: fintech
    b = post("/api/apps", {"name": "fintech-app", "creds": {
        "telegram_token": "654321:FIN_TOKEN",
        "twilio_sid": "ACfintechdemo",
        "stripe_key": "sk_test_fintech",
        "whatsapp_phone_id": "2002002002",
    }})

    # ---- Shop app outbound ----
    post("/telegram/bot123456:SHOP_TOKEN/sendMessage",
         {"chat_id": 987654321, "text": "Your order #1042 has shipped! 🚚"})
    post("/telegram/bot123456:SHOP_TOKEN/sendMessage",
         {"chat_id": 987654321, "text": "Use code WELCOME10 for 10% off your next order.",
          "reply_markup": {"inline_keyboard": [[{"text": "Track order", "url": "https://shop.test/track/1042"}]]}})
    post("/whatsapp/v1/1001001001/messages",
         {"to": "+34600000001", "type": "text", "text": {"body": "Your code is 391827. Confirm your account."}})
    post("/twilio/2010-04-01/Accounts/ACshopdemo/Messages.json",
         {"To": "+34600000002", "From": "+12025550142", "Body": "Shop: your OTP is 482910"})
    post("/stripe/v1/checkout/sessions",
         {"success_url": "https://shop.test/success", "cancel_url": "https://shop.test/cancel",
          "amount_total": 4990, "currency": "usd"})

    # ---- Fintech app outbound ----
    post("/telegram/bot654321:FIN_TOKEN/sendMessage",
         {"chat_id": 111222333, "text": "Payment received: +$250.00 💰"})
    post("/whatsapp/v1/2002002002/messages",
         {"to": "+34600000003", "type": "text", "text": {"body": "Transfer of $1,200.00 completed."}})
    post("/twilio/2010-04-01/Accounts/ACfintechdemo/Messages.json",
         {"To": "+34600000004", "From": "+12025550143", "Body": "Fintech: verification code 774411"})

    # ---- Inbound + webhooks toward the apps ----
    post("/api/webhooks", {"channel": "telegram", "target_url": "http://shop-app.local/webhooks/telegram",
                           "app": "shop-app"})
    post("/api/webhooks", {"channel": "stripe", "target_url": "http://shop-app.local/webhooks/stripe",
                           "app": "shop-app"})
    post("/api/webhooks", {"channel": "whatsapp", "target_url": "http://fintech-app.local/webhooks/whatsapp",
                           "app": "fintech-app"})

    # Inbound message to shop app (webhook unreachable in demo -> recorded as down)
    post("/telegram/client/sendMessage", {"chat_id": 987654321, "text": "Where is my order?"},
         headers={"X-MockPost-App": "shop-app"})

    # Signed Stripe event to shop app
    post("/stripe/simulate_event", {"event_type": "checkout.session.completed",
                                    "overrides": {"amount_total": 4990}},
         headers={"X-MockPost-App": "shop-app"})

    # TOTP secret for the fintech 2FA flow
    totp = post("/api/otp/totp/generate", {"identifier": "user@fintech.test"})
    code = CLIENT.get(f"{BASE}/api/otp/totp/code", params={"identifier": "user@fintech.test"}).json()

    print(f"Seeded demo. apps: {a['name']}, {b['name']}")
    print(f"TOTP secret: {totp['secret']} (otpauth: {totp['otpauth_url'][:60]}...)")
    print(f"TOTP current code: {code['code']}")
    print(f"Panel: {BASE}/")
    time.sleep(0.3)
    md = CLIENT.get(f"{BASE}/api/timeline/markdown").text
    print("\n--- Timeline markdown (first 25 lines) ---")
    print("\n".join(md.splitlines()[:25]))


if __name__ == "__main__":
    main()
