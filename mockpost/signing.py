"""Signing utilities: VAPID (py_vapid), Stripe-Signature and social webhook signatures.

Per-provider webhook signing, replicating each service's real scheme:
- GitHub:    X-Hub-Signature-256 = sha256=HMAC-SHA256(secret, body)
- Facebook:  X-Hub-Signature-256 = sha256=HMAC-SHA256(app_secret, body)
- X:         X-Twitter-Webhooks-Signature = base64(HMAC-SHA256(consumer_secret, body))
- Google:    no webhooks (OAuth uses tokeninfo/revoke instead)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

from mockpost.config import settings


def _hmac_hex(secret: str, body: str, algo: str = "sha256") -> str:
    digest = hmac.new(secret.encode(), body.encode(), getattr(hashlib, algo)).hexdigest()
    return digest


def _hmac_b64(secret: str, body: str) -> str:
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def github_signature(body: str, secret: str) -> str:
    """GitHub X-Hub-Signature-256: sha256=<hmac> over the raw body."""
    return f"sha256={_hmac_hex(secret, body)}"


def verify_github_signature(body: str, signature_header: str, secret: str) -> bool:
    if not signature_header:
        return False
    expected = github_signature(body, secret)
    return hmac.compare_digest(expected, signature_header)


def facebook_signature(body: str, secret: str) -> str:
    """Facebook X-Hub-Signature-256 (Graph API webhooks): sha256=<hmac>."""
    return f"sha256={_hmac_hex(secret, body)}"


def verify_facebook_signature(body: str, signature_header: str, secret: str) -> bool:
    if not signature_header:
        return False
    expected = facebook_signature(body, secret)
    return hmac.compare_digest(expected, signature_header)


def x_signature(body: str, secret: str) -> str:
    """X-Twitter-Webhooks-Signature: base64(HMAC-SHA256(consumer_secret, body))."""
    return _hmac_b64(secret, body)


def verify_x_signature(body: str, signature_header: str, secret: str) -> bool:
    if not signature_header:
        return False
    expected = x_signature(body, secret)
    return hmac.compare_digest(expected, signature_header)


def x_crc_response(crc_token: str, consumer_secret: str) -> str:
    """X (Account Activity API) CRC check: response_token = base64(HMAC-SHA256(crc_token, consumer_secret))."""
    digest = hmac.new(consumer_secret.encode(), crc_token.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def vapid_claims(authorization: str | None) -> dict | None:
    """Claims of a VAPID header, in either scheme, without validating them.

    - RFC 8292 / draft-02: `Authorization: vapid t=<jwt>,k=<public key>`
    - draft-01: `Authorization: WebPush <jwt>`, key in the Crypto-Key header.
      Older clients (pywebpush with version="aesgcm", web-push < 3.3) still
      send this one, so a push service has to read both."""
    if not authorization:
        return None
    scheme, _, rest = authorization.partition(" ")
    try:
        if scheme.lower() == "vapid":
            token = rest.split("t=", 1)[1].split(",", 1)[0]
        elif scheme.lower() == "webpush":
            token = rest.strip()
        else:
            return None
        payload_b64 = token.split(".", 2)[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return None


def verify_vapid(authorization: str | None, audience: str) -> bool:
    """Validate a real VAPID header (py_vapid) and its aud/exp claims.

    py_vapid.verify() checks the ES256 signature against the `k=` key of the
    header; the draft-01 `WebPush <jwt>` scheme carries its key in Crypto-Key,
    so for that one only the claims are checked."""
    if not authorization:
        return False
    scheme = authorization.split(" ", 1)[0].lower()
    if scheme not in ("vapid", "webpush"):
        return False
    try:
        if scheme == "vapid":
            from py_vapid import Vapid02
            if not Vapid02.verify(authorization):
                return False
        claims = vapid_claims(authorization)
        if not claims:
            return False
        if claims.get("aud") != audience:
            return False
        if claims.get("exp", 0) < time.time():
            return False
        return True
    except Exception:
        return False


def stripe_signature(payload: str) -> str:
    """Generate `t=<ts>,v1=<hmac>` over `t=<ts>.<body>` with the local webhook_secret."""
    t = str(int(time.time()))
    signed = f"{t}.{payload}".encode()
    digest = hmac.new(settings.stripe_webhook_secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={t},v1={digest}"


def verify_stripe_signature(payload: str, signature_header: str, tolerance_s: int = 300) -> bool:
    """Verify Stripe-Signature: ignore schemes != v1 (e.g. v0 from test tools)."""
    if not signature_header:
        return False
    pairs = {}
    for item in signature_header.split(","):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            pairs[k] = v
    ts, v1 = pairs.get("t"), pairs.get("v1")
    if not ts or not v1:
        return False
    if abs(int(ts) - time.time()) > tolerance_s:
        return False
    signed = f"{ts}.{payload}".encode()
    expected = hmac.new(settings.stripe_webhook_secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


def vapid_public_key_b64() -> str:
    return settings.vapid_keys["public_b64"]


def _vapid_private() -> ec.EllipticCurvePrivateKey:
    pem = settings.vapid_keys["private_pem"].encode()
    return serialization.load_pem_private_key(pem, password=None)


def sign_vapid(audience: str, contact: str | None = None) -> str:
    """Generate a signed `Authorization: vapid ...` header with the local key
    (for testing the endpoint from the panel/tests)."""
    from py_vapid import Vapid02
    v = Vapid02.from_pem(settings.vapid_keys["private_pem"].encode())
    claims = {
        "aud": audience,
        "exp": int(time.time()) + 3600,
        "sub": contact or settings.vapid_contact,
    }
    return v.sign(claims)["Authorization"]


def url_safe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
