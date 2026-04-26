"""Pre-Task-13 AgentOS client round-trip probe.

Drives the exact SDK surface AgentOSRuntime depends on:
  aget_config -> create_session -> run_agent (with output_schema)
  -> delete_session.

Records the observed shape of each response on stdout in a structured
block, then exits 0 on success, 1 on any deviation from the expected
call shape. Destructive only against its own test session.

Usage (with app.py already running on localhost:7777):
    OPENROUTER_API_KEY=... python -m scripts.agentos_dry_run.client_probe
"""

from __future__ import annotations

import asyncio
import json

from agno.client import AgentOSClient

# Mirrors src.runtime.agentos._AGENT_ACTION_JSON_SCHEMA shape — derived
# from the V1 AgentAction pydantic model. Hardcoded here so the probe has
# zero dependency on src/ so it runs even if src/ is in a broken state.
AGENT_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["EXECUTE_SWAP", "WAIT", "FINISH"]},
        "params": {"type": "object"},
    },
    "required": ["type", "params"],
    "additionalProperties": False,
}

BASE_URL = "http://localhost:7777"
AGENT_ID = "dry-run-agent"
USER_ID = "dry-run-user"


def _report(label: str, obj: object) -> None:
    print(f"---- {label} ----")
    print(f"python type: {type(obj).__name__}")
    print(f"repr: {obj!r}")
    # dump structured fields if available
    fields = None
    for attr in ("model_dump", "__dict__"):
        if hasattr(obj, attr):
            try:
                fields = getattr(obj, attr)
                if callable(fields):
                    fields = fields()
                break
            except Exception as e:  # pragma: no cover
                fields = f"<dump failed: {e}>"
    if fields is not None:
        try:
            print(f"fields: {json.dumps(fields, default=str, indent=2)[:2000]}")
        except Exception as e:
            print(f"fields: <not JSON-serializable: {e}>")


async def main() -> int:
    client = AgentOSClient(base_url=BASE_URL)

    print("==== 1. aget_config ====")
    config = await client.aget_config()
    _report("config", config)
    agents = getattr(config, "agents", None) or []
    ids = [getattr(a, "id", None) for a in agents]
    print(f"agent ids: {ids}")
    if AGENT_ID not in ids:
        print(f"FAIL: {AGENT_ID!r} not in {ids!r}")
        return 1

    print("\n==== 2. create_session ====")
    session = await client.create_session(
        agent_id=AGENT_ID,
        user_id=USER_ID,
        session_name="pre-task-13-gate",
    )
    _report("session", session)
    session_id = getattr(session, "session_id", None)
    if not session_id:
        print("FAIL: session object has no session_id")
        return 1
    print(f"session_id: {session_id}")

    print("\n==== 3a. run_agent (no output_schema) ====")
    baseline = await client.run_agent(
        agent_id=AGENT_ID,
        message=(
            "Return JSON: "
            '{"type": "FINISH", "params": {}}'
        ),
        session_id=session_id,
    )
    _report("run_agent (baseline)", baseline)
    print(f"baseline.content type: {type(getattr(baseline, 'content', None)).__name__}")
    print(f"baseline.content value: {getattr(baseline, 'content', None)!r}")
    print(f"baseline.content_type attr: {getattr(baseline, 'content_type', '<missing>')!r}")

    print("\n==== 3b. run_agent (output_schema) ====")
    structured = await client.run_agent(
        agent_id=AGENT_ID,
        message=(
            "Return a single AgentAction JSON object with fields {type, params}. "
            "Use type=FINISH and params={}."
        ),
        session_id=session_id,
        output_schema=AGENT_ACTION_SCHEMA,
    )
    _report("run_agent (output_schema)", structured)
    sc = getattr(structured, "content", None)
    print(f"structured.content type: {type(sc).__name__}")
    print(f"structured.content value: {sc!r}")
    print(f"structured.content_type attr: {getattr(structured, 'content_type', '<missing>')!r}")

    print("\n==== 4. delete_session ====")
    res = await client.delete_session(session_id=session_id)
    _report("delete_session result", res)

    print("\n==== 5. delete_session (idempotent retry) ====")
    try:
        res2 = await client.delete_session(session_id=session_id)
        print(f"repeat delete returned: {res2!r} (no exception)")
    except Exception as e:
        print(f"repeat delete raised: {type(e).__name__}: {e}")

    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
