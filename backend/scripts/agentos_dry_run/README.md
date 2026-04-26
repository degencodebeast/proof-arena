# Pre-Task-13 AgentOS live dry-run

Minimal repeatable gate that validates the real AgentOS SDK round-trip
against the `AgentOSRuntime` wrapper. Intended to run **before** Task 13
wires up the deploy saga end-to-end.

Three files, all throwaway except this folder:

- `app.py` — minimal local AgentOS with one pre-registered test agent
  (`dry-run-agent`), SQLite DB at `/tmp/agentos_dry_run.db`, no auth.
- `client_probe.py` — raw `AgentOSClient` probe that prints exact payload
  shapes (`aget_config`, `create_session`, `run_agent` with & without
  `output_schema`, `delete_session`, repeat-delete).
- `wrapper_probe.py` — exercises the V2 `AgentOSRuntime` wrapper against
  the running app: deploy → invoke_decide → teardown → repeat-teardown.

## Run

From `agent-rank/backend/` with the venv activated and
`OPENROUTER_API_KEY` in scope (e.g. sourced from
`agent-rank/.env`):

```bash
# 1. Start AgentOS
rm -f /tmp/agentos_dry_run.db
python -m scripts.agentos_dry_run.app &

# 2. (optional) Raw SDK probe — shape-only evidence.
python -m scripts.agentos_dry_run.client_probe

# 3. Wrapper end-to-end
python -m scripts.agentos_dry_run.wrapper_probe

# 4. Stop
kill %1
```

## What this proves

| Contract claim | Evidence path |
|---|---|
| `create_session` returns `AgentSessionDetailSchema` with `.session_id` | `client_probe` section 2 |
| `run_agent` returns `RunOutput` with `.content` as string JSON | `client_probe` section 3a |
| `output_schema` kwarg is accepted by SDK but PROVIDER-DEPENDENT | `client_probe` section 3b |
| `delete_session` returns `None`; repeat is idempotent at server | `client_probe` sections 4, 5 |
| Wrapper `deploy → invoke_decide → teardown` works end-to-end | `wrapper_probe` happy path |
| Wrapper surfaces parse failures as `AgentOSRuntimeError` cleanly | `wrapper_probe` with a bad LLM response |

See `.taskmaster/docs/task12-agentos-contract-note.md` §1 "LIVE GATE" +
§4 "A7/A8" for the locked findings.

## Caveats

- Requires `OPENROUTER_API_KEY` (or any Agno-supported LLM key) reachable
  in the environment. Agent quality isn't tested — the SDK round-trip is.
- `app.py` pins `openai/gpt-4o-mini` via OpenRouter. Fine for this gate.
  For V2 production, pick a model that honors Agno structured outputs if
  you want to enable `use_output_schema=True`.
- Not wired into CI. This is an operational gate, not a unit test. The
  placeholder `@pytest.mark.integration` test lives at
  `backend/tests/test_task_12_agentos_contract.py::test_live_agentos_round_trip`.
