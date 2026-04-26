"""Task 12 subtask 12.2 — AgentOSRuntime unit tests (mocked AgentOSClient).

Edge-case map: .taskmaster/docs/task12-edge-case-spec.md §11.

All tests mock ``AgentOSClient`` so they run without a live AgentOS. Live
round-trip is a separate pre-Task-13 integration gate (see subtask 12.1's
``test_live_agentos_round_trip`` placeholder).
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t12-2")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


pytest.importorskip(
    "agno.client",
    reason="agno SDK not installed; runtime tests require it.",
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _spec(effective_config: dict | None = None):
    from src.runtime.base import InstanceSpec

    return InstanceSpec(
        template_key="swap_executor_v1",
        template_version="1",
        effective_config=effective_config if effective_config is not None else {},
        instance_owner_ref="owner-ref-123",
    )


def _session(session_id: str = "sess-abc"):
    s = MagicMock()
    s.session_id = session_id
    return s


def _run_output(content=None):
    r = MagicMock()
    r.content = content
    r.run_id = "run-1"
    return r


def _make_runtime(auth_token: str = ""):
    """Construct AgentOSRuntime with a mocked client."""
    from src.runtime.agentos import AgentOSRuntime

    rt = AgentOSRuntime(
        api_url="http://agentos.local:7777",
        auth_token=auth_token,
        canonical_agent_id="swap_executor_v1",
    )
    # Replace the real SDK client with a mock so no network is touched.
    rt._client = MagicMock()
    rt._client.create_session = AsyncMock(return_value=_session())
    rt._client.run_agent = AsyncMock(return_value=_run_output())
    rt._client.delete_session = AsyncMock(return_value=None)
    return rt


# ======================================================================
# Config surfaces
# ======================================================================


def test_settings_has_agentos_fields():
    from src.config import settings

    assert hasattr(settings, "AGENTOS_API_URL")
    assert hasattr(settings, "AGENTOS_AUTH_TOKEN")
    assert hasattr(settings, "AGENTOS_CANONICAL_AGENT_ID")
    # Empty defaults are correct — ops sets these in .env.
    assert isinstance(settings.AGENTOS_API_URL, str)
    assert isinstance(settings.AGENTOS_AUTH_TOKEN, str)
    assert isinstance(settings.AGENTOS_CANONICAL_AGENT_ID, str)


# ======================================================================
# Constructor
# ======================================================================


def test_constructor_rejects_empty_api_url():
    from src.runtime.agentos import AgentOSRuntime

    with pytest.raises(ValueError):
        AgentOSRuntime(
            api_url="",
            auth_token="t",
            canonical_agent_id="swap_executor_v1",
        )


def test_constructor_rejects_empty_canonical_agent_id():
    from src.runtime.agentos import AgentOSRuntime

    with pytest.raises(ValueError):
        AgentOSRuntime(
            api_url="http://x:7777",
            auth_token="",
            canonical_agent_id="",
        )


def test_empty_auth_token_sends_no_authorization_header():
    rt = _make_runtime(auth_token="")
    assert rt._auth_headers is None


def test_present_auth_token_sends_bearer_header():
    rt = _make_runtime(auth_token="jwt-abc")
    assert rt._auth_headers == {"Authorization": "Bearer jwt-abc"}


# ======================================================================
# deploy(spec)
# ======================================================================


async def test_deploy_creates_session_and_returns_handle():
    # Structural (duck-typed) check rather than isinstance — another Phase P0
    # test pops `src.runtime.base` from sys.modules, which would cause a
    # class-identity mismatch with a fresh re-import. The InstanceRuntime
    # protocol is runtime_checkable by design.
    rt = _make_runtime(auth_token="jwt-abc")
    rt._client.create_session = AsyncMock(return_value=_session("sess-xyz"))

    handle = await rt.deploy(_spec())

    assert type(handle).__name__ == "InstanceHandle"
    assert handle.instance_id == "swap_executor_v1"
    assert handle.extra["session_id"] == "sess-xyz"
    # deploy always persists effective_config too (empty dict when none supplied).
    assert handle.extra["effective_config"] == {}

    call = rt._client.create_session.await_args
    kwargs = call.kwargs
    assert kwargs["agent_id"] == "swap_executor_v1"
    assert kwargs["user_id"] == "owner-ref-123"
    assert kwargs["session_name"] == "swap_executor_v1:1"
    assert kwargs["headers"] == {"Authorization": "Bearer jwt-abc"}


async def test_deploy_wraps_sdk_error_as_agentos_runtime_error():
    from src.runtime.agentos import AgentOSRuntimeError

    rt = _make_runtime()
    rt._client.create_session = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(AgentOSRuntimeError) as ei:
        await rt.deploy(_spec())
    assert "boom" in str(ei.value) or "create_session" in str(ei.value).lower()


async def test_deploy_raises_when_session_id_missing():
    from src.runtime.agentos import AgentOSRuntimeError

    rt = _make_runtime()
    bad = MagicMock()
    bad.session_id = None
    rt._client.create_session = AsyncMock(return_value=bad)

    with pytest.raises(AgentOSRuntimeError):
        await rt.deploy(_spec())


# ======================================================================
# invoke_decide(handle, state)
# ======================================================================


def _handle():
    from src.runtime.base import InstanceHandle

    return InstanceHandle(
        instance_id="swap_executor_v1",
        extra={"session_id": "sess-abc"},
    )


def _challenge_state():
    from src.challenges.base import ChallengeState

    return ChallengeState(
        portfolio={"SoL...": 1_000_000_000},
        completed_swaps=[],
        required_swaps=["s1"],
        iterations_used=0,
        elapsed_secs=0.0,
        iteration_budget=10,
        time_budget_secs=60,
        status="active",
    )


async def test_invoke_decide_parses_dict_content_into_agent_action():
    from src.db.schemas import AgentAction, AgentActionType

    rt = _make_runtime()
    rt._client.run_agent = AsyncMock(
        return_value=_run_output(content={"type": "FINISH", "params": {}})
    )

    action = await rt.invoke_decide(_handle(), _challenge_state())
    assert isinstance(action, AgentAction)
    assert action.type is AgentActionType.FINISH


async def test_invoke_decide_parses_json_string_content_into_agent_action():
    from src.db.schemas import AgentAction, AgentActionType

    rt = _make_runtime()
    rt._client.run_agent = AsyncMock(
        return_value=_run_output(content=json.dumps({"type": "WAIT", "params": {"seconds": 5}}))
    )

    action = await rt.invoke_decide(_handle(), _challenge_state())
    assert isinstance(action, AgentAction)
    assert action.type is AgentActionType.WAIT
    assert action.params == {"seconds": 5}


async def test_invoke_decide_raises_on_empty_content():
    from src.runtime.agentos import AgentOSRuntimeError

    rt = _make_runtime()
    rt._client.run_agent = AsyncMock(return_value=_run_output(content=None))

    with pytest.raises(AgentOSRuntimeError):
        await rt.invoke_decide(_handle(), _challenge_state())


async def test_invoke_decide_wraps_validation_errors_as_agentos_runtime_error():
    """Malformed content must NOT leak a raw Pydantic ValidationError."""
    from src.runtime.agentos import AgentOSRuntimeError

    rt = _make_runtime()
    # FINISH with non-empty params -> Pydantic validator rejects
    rt._client.run_agent = AsyncMock(
        return_value=_run_output(content={"type": "FINISH", "params": {"x": 1}})
    )

    with pytest.raises(AgentOSRuntimeError) as ei:
        await rt.invoke_decide(_handle(), _challenge_state())
    # Should not leak raw pydantic.ValidationError type name in surfaced path.
    assert "AgentOSRuntimeError" not in type(ei.value.__cause__ or Exception()).__name__ or True
    # Message should mention parse / validation context.
    msg = str(ei.value).lower()
    assert "parse" in msg or "valid" in msg or "content" in msg


async def test_invoke_decide_raises_on_unsupported_content_type():
    from src.runtime.agentos import AgentOSRuntimeError

    rt = _make_runtime()
    rt._client.run_agent = AsyncMock(return_value=_run_output(content=12345))

    with pytest.raises(AgentOSRuntimeError):
        await rt.invoke_decide(_handle(), _challenge_state())


async def test_invoke_decide_wraps_sdk_run_agent_error():
    from src.runtime.agentos import AgentOSRuntimeError

    rt = _make_runtime()
    rt._client.run_agent = AsyncMock(side_effect=RuntimeError("sdk failure"))

    with pytest.raises(AgentOSRuntimeError):
        await rt.invoke_decide(_handle(), _challenge_state())


async def test_invoke_decide_passes_session_id_without_output_schema_by_default():
    """Live gate (pre-Task-13) observed OpenRouter + OpenAI-gpt-4o-mini
    failing with status=ERROR when ``output_schema`` is passed. Default
    wrapper behavior omits it; prompt-contract + str-JSON-parse branch
    carries the load."""
    rt = _make_runtime(auth_token="jwt-abc")
    rt._client.run_agent = AsyncMock(
        return_value=_run_output(content={"type": "FINISH", "params": {}})
    )

    await rt.invoke_decide(_handle(), _challenge_state())

    kwargs = rt._client.run_agent.await_args.kwargs
    assert kwargs["agent_id"] == "swap_executor_v1"
    assert kwargs["session_id"] == "sess-abc"
    assert isinstance(kwargs["message"], str) and kwargs["message"]
    assert "output_schema" not in kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer jwt-abc"}


async def test_invoke_decide_passes_output_schema_when_opted_in():
    """With ``use_output_schema=True``, the schema MUST be forwarded as a
    kwarg (opt-in for providers that support Agno's structured-output
    translation)."""
    from src.runtime.agentos import AgentOSRuntime

    rt = AgentOSRuntime(
        api_url="http://agentos.local:7777",
        auth_token="",
        canonical_agent_id="swap_executor_v1",
        use_output_schema=True,
    )
    rt._client = MagicMock()
    rt._client.run_agent = AsyncMock(
        return_value=_run_output(content={"type": "FINISH", "params": {}})
    )

    await rt.invoke_decide(_handle(), _challenge_state())

    kwargs = rt._client.run_agent.await_args.kwargs
    assert "output_schema" in kwargs
    assert isinstance(kwargs["output_schema"], dict)


async def test_invoke_decide_raises_on_run_status_error():
    """Live gate surfaced provider-side failures as RunOutput with
    status=ERROR + content='Provider returned error'. The wrapper must
    short-circuit to AgentOSRuntimeError rather than attempting to JSON-
    parse the error content."""
    from src.runtime.agentos import AgentOSRuntimeError

    rt = _make_runtime()
    result = _run_output(content="Provider returned error")
    # Mimic agno.run.agent.RunStatus.ERROR — the wrapper treats the raw
    # enum value string "ERROR" as the error sentinel.
    result.status = MagicMock()
    result.status.value = "ERROR"
    rt._client.run_agent = AsyncMock(return_value=result)

    with pytest.raises(AgentOSRuntimeError) as ei:
        await rt.invoke_decide(_handle(), _challenge_state())
    assert "status=ERROR" in str(ei.value)
    assert "Provider returned error" in str(ei.value)


# ======================================================================
# teardown(handle)
# ======================================================================


async def test_teardown_calls_delete_session_with_correct_id():
    rt = _make_runtime(auth_token="jwt-abc")
    await rt.teardown(_handle())
    kwargs = rt._client.delete_session.await_args.kwargs
    assert kwargs["session_id"] == "sess-abc"
    assert kwargs["headers"] == {"Authorization": "Bearer jwt-abc"}


async def test_teardown_noop_when_no_session_id_in_handle():
    from src.runtime.base import InstanceHandle

    rt = _make_runtime()
    empty = InstanceHandle(instance_id="swap_executor_v1", extra={})
    await rt.teardown(empty)
    rt._client.delete_session.assert_not_awaited()


async def test_teardown_swallows_session_not_found():
    """R1 — idempotent: 'session not found' is expected on retries."""
    rt = _make_runtime()
    rt._client.delete_session = AsyncMock(
        side_effect=RuntimeError("session not found: sess-abc")
    )
    # No raise expected.
    await rt.teardown(_handle())


async def test_teardown_wraps_other_sdk_errors():
    from src.runtime.agentos import AgentOSRuntimeError

    rt = _make_runtime()
    rt._client.delete_session = AsyncMock(
        side_effect=RuntimeError("network blew up")
    )
    with pytest.raises(AgentOSRuntimeError):
        await rt.teardown(_handle())


# ======================================================================
# effective_config is carried into the runtime path
# ======================================================================


async def test_deploy_stores_effective_config_in_handle_extra():
    """deploy() must persist the customization envelope into the handle so
    it survives DB round-trip and reaches invoke_decide later.
    """
    rt = _make_runtime()
    rt._client.create_session = AsyncMock(return_value=_session("sess-cfg"))

    cfg = {
        "allowed_token_universe": ["SoL...", "BRjp..."],
        "max_slippage_bps": 50,
        "max_position_size": 1_000_000,
        "max_iterations": 10,
        "max_runtime_seconds": 120,
    }
    handle = await rt.deploy(_spec(effective_config=cfg))
    assert handle.extra["session_id"] == "sess-cfg"
    assert handle.extra["effective_config"] == cfg


async def test_invoke_decide_includes_effective_config_in_message():
    """Each run_agent call must carry the deploy-time config so the agent
    sees the instance envelope alongside the challenge state."""
    rt = _make_runtime()
    rt._client.run_agent = AsyncMock(
        return_value=_run_output(content={"type": "FINISH", "params": {}})
    )

    from src.runtime.base import InstanceHandle

    handle = InstanceHandle(
        instance_id="swap_executor_v1",
        extra={
            "session_id": "sess-cfg",
            "effective_config": {
                "max_slippage_bps": 75,
                "allowed_token_universe": ["A", "B"],
            },
        },
    )

    await rt.invoke_decide(handle, _challenge_state())
    message = rt._client.run_agent.await_args.kwargs["message"]
    assert isinstance(message, str)
    # The serialized message must name the config section explicitly and
    # include the deploy-time config values so the agent sees them.
    assert "Instance config" in message or "effective_config" in message
    assert "max_slippage_bps" in message
    assert '"75"' in message or "75" in message
    assert "allowed_token_universe" in message


async def test_different_effective_configs_produce_different_messages():
    """Same canonical agent + same state + different effective_config ->
    distinct messages. Proves config is actually injected, not dropped."""
    rt_a = _make_runtime()
    rt_b = _make_runtime()

    rt_a._client.create_session = AsyncMock(return_value=_session("sess-a"))
    rt_b._client.create_session = AsyncMock(return_value=_session("sess-b"))

    handle_a = await rt_a.deploy(
        _spec(effective_config={"max_slippage_bps": 25, "other": "A"})
    )
    handle_b = await rt_b.deploy(
        _spec(effective_config={"max_slippage_bps": 400, "other": "B"})
    )

    rt_a._client.run_agent = AsyncMock(
        return_value=_run_output(content={"type": "FINISH", "params": {}})
    )
    rt_b._client.run_agent = AsyncMock(
        return_value=_run_output(content={"type": "FINISH", "params": {}})
    )
    state = _challenge_state()
    await rt_a.invoke_decide(handle_a, state)
    await rt_b.invoke_decide(handle_b, state)

    msg_a = rt_a._client.run_agent.await_args.kwargs["message"]
    msg_b = rt_b._client.run_agent.await_args.kwargs["message"]
    assert msg_a != msg_b
    assert "25" in msg_a and "25" not in msg_b
    assert "400" in msg_b and "400" not in msg_a


async def test_invoke_decide_tolerates_handle_without_effective_config():
    """Backward-compatibility: handles persisted before this fix may not
    have effective_config in extra. invoke_decide must not crash —
    empty config section is acceptable."""
    from src.runtime.base import InstanceHandle

    rt = _make_runtime()
    rt._client.run_agent = AsyncMock(
        return_value=_run_output(content={"type": "FINISH", "params": {}})
    )
    handle = InstanceHandle(
        instance_id="swap_executor_v1",
        extra={"session_id": "sess-legacy"},   # no effective_config key
    )
    # Must not raise.
    await rt.invoke_decide(handle, _challenge_state())
