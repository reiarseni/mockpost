"""Security tests: webhook URL validation (SSRF guards)."""

from __future__ import annotations

import pytest

from mockpost.webhooks import _validate_webhook_url


def test_blocked_metadata_cloud():
    with pytest.raises(ValueError):
        _validate_webhook_url("http://169.254.169.254/latest/meta-data/")


def test_blocked_link_local():
    with pytest.raises(ValueError):
        _validate_webhook_url("http://169.254.100.10:8080/hook")


def test_blocked_non_http_scheme():
    with pytest.raises(ValueError):
        _validate_webhook_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        _validate_webhook_url("dict://127.0.0.1:11211/")


def test_allowed_localhost_and_lan():
    # loopback y LAN privada son el caso de uso normal de un emulador local
    _validate_webhook_url("http://127.0.0.1:9999/hook")
    _validate_webhook_url("http://localhost:8090/hook")
    _validate_webhook_url("http://192.168.1.20:8080/webhooks/x")
    _validate_webhook_url("http://10.0.0.5:3000/hook")
