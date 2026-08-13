# ---- build stage: install the package into a clean venv ----
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY mockpost/ mockpost/
COPY mockpost_mcp/ mockpost_mcp/

RUN pip install --no-cache-dir uv && \
    uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python .

# ---- runtime stage ----
FROM python:3.12-slim

ENV PATH="/opt/venv/bin:$PATH" \
    MOCKPOST_DB_PATH=/app/data/mockpost.db \
    MOCKPOST_HOST=0.0.0.0

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv

EXPOSE 8090 1025

CMD ["mockpost"]
