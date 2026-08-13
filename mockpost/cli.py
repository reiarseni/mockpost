"""`mockpost` console entry point: starts the MockPost server (uvicorn)."""

from __future__ import annotations

import os

import uvicorn

from mockpost.config import settings


def main() -> None:
    # Bind localhost by default: MockPost has no auth by design, so it must
    # never be reachable from the network unless the user opts in explicitly.
    uvicorn.run(
        "mockpost.main:app",
        host=os.environ.get("MOCKPOST_HOST", "127.0.0.1"),
        port=settings.http_port,
        log_level=os.environ.get("MOCKPOST_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
