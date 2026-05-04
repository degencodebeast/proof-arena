# Proof Arena AgentOS Service

Product-owned AgentOS hosted-runtime process for Proof Arena V2. Runs
as a separate Coolify service alongside the backend; the backend
reaches it via `AGENTOS_API_URL` and creates per-instance sessions
against the canonical agent id resolved per template_key (multi-template
via `AGENTOS_CANONICAL_AGENT_IDS_JSON`, with legacy single-template
fallback to `AGENTOS_CANONICAL_AGENT_ID`).

**This is not `agno-agents/`.** That folder is examples / reference
only. Product runtime code lives here.

## Why a sibling package, not `backend/src/runtime/agentos_app.py`

Task 12.3 enforces an import boundary — `agno.client` may only be
imported in `backend/src/runtime/agentos.py` (the *client* side of
the AgentOS contract). This package is the *server* side; it imports
`agno.os.AgentOS`, `agno.agent.Agent`, and `agno.models.*`. Keeping
it sibling to `backend/` keeps the boundary scan simple — the test
walks `backend/src/**` and ignores everything outside that tree.

If a future change moves this code into `backend/src/`, that change
must also update `backend/tests/test_task_12_import_boundary.py` in
the SAME commit, with explicit rationale.

## Decision-only contract (V2 trust boundary)

The canonical agent declared here:
- Receives serialized challenge state + effective config (via
  `AgentOSClient.run_agent(message=…)`).
- Returns a structured `AgentAction` (one of `EXECUTE_SWAP`, `WAIT`,
  `FINISH`).
- Has **no tools** (`tools=[]`). Wallet, Orca, swap execution,
  evidence recording, scoring all live in the backend runner.

If you see `tools=[...]` non-empty in `agent.py`, that is a contract
break.

## Single source of truth

`canonical_template_contract.py` re-exports `SWAP_EXECUTOR_V1_SEED`
from `backend/src/services/template_service.py` verbatim. Forking
that dict here is forbidden — `tests/test_seed_is_single_source_of_truth.py`
asserts object identity.

## Env-pair contract

| Variable | Owned by | Default | Purpose |
|---|---|---|---|
| `AGENTOS_API_URL` | backend | `""` | Backend → AgentOS URL |
| `AGENTOS_AUTH_TOKEN` | backend | `""` | Bearer JWT (optional) |
| `AGENTOS_CANONICAL_AGENT_ID` | backend | `""` | Agent id backend creates sessions against |
| `AGENTOS_CANONICAL_AGENT_ID` (pun: same name) | agentos_app | `"swap_executor_v1"` | Agent id declared at startup |
| `AGENTOS_HOST` | agentos_app | `0.0.0.0` | Bind (interpolated by Dockerfile CMD) |
| `AGENTOS_PORT` | agentos_app | `7000` | Bind (interpolated by Dockerfile CMD) |
| `AGENTOS_DATABASE_URL` | agentos_app | `""` | Agno session DB; use `postgresql+psycopg://...` in Coolify |
| `AGENTOS_LLM_PROVIDER` | agentos_app | `"openrouter"` | Model vendor |
| `AGENTOS_LLM_MODEL` | agentos_app | `"openai/gpt-4o-mini"` | Model id |
| `OPENROUTER_API_KEY` | agentos_app | `""` | Vendor key (SDK-canonical name, NOT prefixed) |
| `ANTHROPIC_API_KEY` | agentos_app | `""` | Vendor key (SDK-canonical name, NOT prefixed) |
| `OPENAI_API_KEY` | agentos_app | `""` | Vendor key (SDK-canonical name, NOT prefixed) |
| `GOOGLE_API_KEY` | agentos_app | `""` | Vendor key (SDK-canonical name, NOT prefixed) |

Live Coolify deploys should set `AGENTOS_DATABASE_URL` so
`AgentOSClient.create_session(...)` works. The backend's `DATABASE_URL`
uses `postgresql+asyncpg://...`; AgentOS uses Agno's Postgres adapter,
so use the same Postgres credentials with `postgresql+psycopg://...`.
Agno creates the `proof_arena_agentos_sessions` table automatically if
it does not exist.

The backend's per-template canonical agent ids MUST agree with what the
AgentOS process declared at startup. Legacy single-template deploys read
`AGENTOS_CANONICAL_AGENT_ID`; multi-template deploys read
`AGENTOS_CANONICAL_AGENT_IDS_JSON` (a JSON dict keyed by template_key,
e.g. `{"swap_executor_v1": "...", "rebalance_executor_v1": "..."}`).

The legacy `AGENTOS_CANONICAL_AGENT_ID` env var is validated by
`scripts/smoke.py`, which checks single-agent contract drift.
Multi-template dispatch (via `AGENTOS_CANONICAL_AGENT_IDS_JSON`) is
resolved at backend runtime construction by `get_canonical_agent_ids()`
in `backend/src/config.py`. Adding multi-template smoke validation is
a future operator-tool enhancement.

**Env-alias implementation note.** Each operational field in
`config.py` uses `Field(validation_alias="AGENTOS_...")` so the
documented env name actually binds. A bare-field-name `BaseSettings`
class would otherwise read `CANONICAL_AGENT_ID` (without prefix) —
that is a regression guard pinned by `tests/test_canonical_contract.py::test_canonical_agent_id_env_override`
and the sibling T11-T13 tests.

**Why vendor keys are NOT `AGENTOS_`-prefixed.** The agno SDK reads
`OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / etc. with their canonical
names. The V1 backend env shares them. Double-prefixing would force
operators to set every vendor key twice — once for the backend, once
for AgentOS. T13 negative-guards that the prefixed form is rejected.

## Run locally

```bash
cd agent-rank
# Activate the agentos_app pyproject env (separate from backend's).
uv venv agentos_app/.venv
source agentos_app/.venv/bin/activate
uv pip install -e agentos_app

# Backend src must be importable for the SoT seed.
export PYTHONPATH=$PWD/backend:$PWD

export OPENROUTER_API_KEY=...   # optional for boot; required for runs
uvicorn agentos_app.main:app --host 0.0.0.0 --port 7000
```

## Run in Coolify

Build context = `agent-rank/`. Dockerfile path = `agentos_app/Dockerfile`.
Image bundles `backend/src/` so the SoT import resolves. See
`scripts/v2_infra.md` for the full Coolify provisioning playbook.

## Runtime dependencies

`pyproject.toml` declares the LLM provider SDK closure required by
`SUPPORTED_PROVIDERS` in `agent.py`:

- `openai>=1.0.0` — needed by both the default `openrouter` provider
  and the `openai` provider. Agno's openrouter module imports
  `openai.types.chat` at module load time; without this the AgentOS
  process crashes at startup.
- `psycopg[binary]>=3.1` — required by Agno's `PostgresDb` session
  store used by the live `/sessions` API.
- `anthropic>=0.40.0` — Claude provider.
- `google-genai>=1.0.0` — Gemini provider.

If `SUPPORTED_PROVIDERS` ever changes, update these deps to match.
T14 (`test_supported_providers_importable_under_declared_deps`) is the
regression guard.

## Smoke

```bash
AGENTOS_API_URL=http://agentos:7000 \
AGENTOS_CANONICAL_AGENT_ID=swap_executor_v1 \
python -m agentos_app.scripts.smoke
```

Pass `--create-session` to additionally exercise session creation.

## Tests

```bash
cd agent-rank
PYTHONPATH=$PWD/backend:$PWD uv run --project agentos_app pytest agentos_app/tests/ -q
```
