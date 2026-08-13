"""Internal API /api/messages: list, detail, delete (filterable by app)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Query

from mockpost.apps import get_app_by_name
from mockpost.request_ctx import get_test_id
from mockpost.store import clear_channel, get_message, list_messages

router = APIRouter(prefix="/api", tags=["api"])


async def _app_id_from_name(app: str | None) -> str | None:
    if not app:
        return None
    a = await get_app_by_name(app)
    return a["id"] if a else None


@router.get("/messages")
async def api_list_messages(request: Request, channel: str | None = None,
                            status: str | None = None, app: str | None = None,
                            limit: int = Query(20, le=500)):
    test_id = get_test_id(request)
    app_id = await _app_id_from_name(app)
    return await list_messages(channel=channel, test_id=test_id, status=status,
                               limit=limit, app_id=app_id)


@router.get("/messages/{message_id}")
async def api_get_message(message_id: str):
    msg = await get_message(message_id)
    if not msg:
        return {"error": "not_found", "message_id": message_id}
    return msg


@router.delete("/messages")
async def api_clear_messages(request: Request, channel: str | None = None, app: str | None = None):
    test_id = get_test_id(request)
    app_id = await _app_id_from_name(app)
    deleted = await clear_channel(channel, test_id, app_id)
    return {"deleted": deleted, "channel": channel, "test_id": test_id, "app": app}
