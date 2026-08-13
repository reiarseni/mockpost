"""Request context extraction: test_id and app.

- test_id: X-MockPost-Test-ID header or query param (run within an app).
- app: the real app is identified by its fake credentials (resolved by the
  channel router via apps.resolve_app); simulation (MCP/panel) picks it with
  the X-MockPost-App header (registered app name).
"""

from __future__ import annotations

from fastapi import Request

from mockpost.apps import get_app_by_name


def get_test_id(request: Request) -> str | None:
    return request.headers.get("X-MockPost-Test-ID") or request.query_params.get("test_id")


async def get_app_id(request: Request) -> str | None:
    """App picked explicitly (simulation): X-MockPost-App header with the name."""
    name = request.headers.get("X-MockPost-App") or request.query_params.get("app")
    if not name:
        return None
    app = await get_app_by_name(name)
    return app["id"] if app else None
