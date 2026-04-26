# Proof Arena AgentOS — product-owned hosted runtime service.
#
# Coolify-deployable image. Mirrors the backend Dockerfile pattern
# (Python 3.12 + uv) and bundles `backend/src` so
# `canonical_template_contract` can import `SWAP_EXECUTOR_V1_SEED` as
# the single source of truth.
#
# Build context: `agent-rank/` (the monorepo root). NOT
# `agent-rank/agentos_app/`. Build:
#
#   cd agent-rank
#   docker build -f agentos_app/Dockerfile -t proof-arena-agentos:latest .

FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# Bundle backend `src/` so the SoT seed import resolves at runtime.
# We do NOT copy the whole backend (alembic, tests, etc.) — only the
# Python tree the AgentOS service needs to import.
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/src ./backend/src

# AgentOS service code.
COPY agentos_app ./agentos_app

# uv install — the agentos_app pyproject lists agno + uvicorn +
# pydantic-settings. Backend deps are NOT installed here; only the
# `src/services/template_service` import path is exercised, and that
# import only needs `pydantic` + `sqlalchemy` (already pulled by agno).
COPY agentos_app/pyproject.toml ./pyproject.toml
RUN uv sync --no-dev

# Make `agentos_app.*` and `src.*` importable. The Dockerfile copies
# `backend/src` to `/app/backend/src`; PYTHONPATH includes
# `/app/backend` so `from src.services.template_service import …` works.
ENV PYTHONPATH=/app:/app/backend

EXPOSE 7000

# Shell-form CMD via `sh -c` so the documented AGENTOS_HOST / AGENTOS_PORT
# env vars actually drive the uvicorn bind. Defaults (`0.0.0.0` / `7000`)
# match EXPOSE above. `exec` makes uvicorn replace sh as PID 1 so SIGTERM
# from Coolify shuts it down cleanly.
CMD ["sh", "-c", "exec uv run uvicorn agentos_app.main:app --host \"${AGENTOS_HOST:-0.0.0.0}\" --port \"${AGENTOS_PORT:-7000}\""]
