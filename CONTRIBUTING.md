# Contributing to MockPost

Thanks for helping! MockPost is a local emulator that keeps every message
inside your machine — contributions that keep that promise are always welcome.

## How to contribute

1. **Open an issue first** for bugs and feature ideas, or pick an existing one.
2. Fork the repo and create a branch: `git checkout -b feat/my-change`.
3. Keep changes focused; add tests for new behavior.
4. Run checks before pushing:
   ```bash
   python -m compileall -q app mcp_server
   ```
5. Open a pull request describing what and why.

## Development setup

```bash
uv venv && uv pip install -r requirements.txt
uv run uvicorn app.main:app --port 8090
```

## Guidelines

- English only in code, UI strings and docs.
- No real credentials anywhere — MockPost generates local secrets.
- Keep the single-SQLite-file architecture; it's a feature, not a limitation.
- If you add a channel, register it in `/config`, the README table and the
  MCP tools where applicable.

## Code of conduct

Be kind and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
