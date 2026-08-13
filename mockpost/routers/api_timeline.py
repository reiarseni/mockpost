"""Internal API /api/timeline: JSON and Markdown over build_timeline()."""

from __future__ import annotations

from fastapi import APIRouter, Request, Query
from fastapi.responses import PlainTextResponse

from mockpost.apps import get_app_by_name
from mockpost.request_ctx import get_test_id
from mockpost.timeline_builder import build_timeline, timeline_markdown

router = APIRouter(prefix="/api/timeline", tags=["api"])


async def _app_id(app: str | None) -> str | None:
    if not app:
        return None
    a = await get_app_by_name(app)
    return a["id"] if a else None


@router.get("")
async def api_timeline_json(request: Request, since: str | None = None,
                            channels: list[str] | None = Query(None), limit: int = Query(200, le=1000),
                            app: str | None = None):
    test_id = get_test_id(request)
    app_id = await _app_id(app)
    events = await build_timeline(since=since, channels=channels, test_id=test_id,
                                  limit=limit, app_id=app_id)
    return [e.__dict__ for e in events]


@router.get("/markdown", response_class=PlainTextResponse)
async def api_timeline_markdown(request: Request, since: str | None = None,
                                channels: list[str] | None = Query(None), limit: int = Query(200, le=1000),
                                app: str | None = None):
    test_id = get_test_id(request)
    app_id = await _app_id(app)
    events = await build_timeline(since=since, channels=channels, test_id=test_id,
                                  limit=limit, app_id=app_id)
    return timeline_markdown(events)
