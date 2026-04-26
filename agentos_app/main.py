"""ASGI entrypoint — `uvicorn agentos_app.main:app`.

Module-level ``app`` is what Uvicorn binds to. Coolify's deploy
command (see Dockerfile + ``scripts/v2_infra.md``) runs:

    uvicorn agentos_app.main:app --host 0.0.0.0 --port 7000
"""

from __future__ import annotations

from agentos_app.app import build_agentos_app

app = build_agentos_app()
