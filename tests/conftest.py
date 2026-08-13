"""Shared fixtures: an isolated MockPost server (real uvicorn) with a temp DB.

We run the real server instead of TestClient because FastAPI 0.141+ mounts
routers lazily (`_IncludedRouter`) and starlette's TestClient does not
materialize them — the real uvicorn does, and this also exercises the SMTP.

Each test gets its own HTTP and SMTP port (settings.smtp_port is mutated
before the server starts, since `mockpost.config.settings` is a singleton),
and we wait for the server thread to actually stop before yielding the next
fixture.
"""

from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
import uuid

import httpx
import pytest
import uvicorn


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def client():
    tmpdir = tempfile.mkdtemp(prefix="mockpost-test-")
    db_path = os.path.join(tmpdir, f"test-{uuid.uuid4().hex[:8]}.db")
    os.environ["MOCKPOST_DB_PATH"] = db_path

    from mockpost import config as cfg
    from mockpost.main import app

    # settings is a singleton: patch ports and DB path per test before lifespan
    http_port = _free_port()
    smtp_port = _free_port()
    cfg.settings.db_path = db_path
    cfg.settings.smtp_port = smtp_port
    os.environ["MOCKPOST_HTTP_PORT"] = str(http_port)
    os.environ["MOCKPOST_SMTP_PORT"] = str(smtp_port)
    os.environ["MOCKPOST_URL"] = f"http://127.0.0.1:{http_port}"

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=http_port,
                                           log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{http_port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/health", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)

    with httpx.Client(base_url=base, timeout=10.0) as c:
        c.smtp_port = smtp_port
        yield c

    server.should_exit = True
    thread.join(timeout=10)
