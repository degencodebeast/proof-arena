"""Task 12 subtask 12.1 — AgentOS SDK contract-lock tests.

Locks the real Agno Python SDK surface that ``AgentOSRuntime`` depends on.
Guards against SDK version drift breaking the wrapper.

See:
- ``.taskmaster/docs/task12-agentos-contract-note.md`` (authoritative AgentOS contract)
- ``.taskmaster/docs/task12-edge-case-spec.md`` §11 (test map)

If ``agno`` is not installed in the current environment, these tests skip
cleanly with a clear reason — the runtime package must still import safely
without the SDK (Task 12.3 invariant IB3).

A live dry-run placeholder (``test_live_agentos_round_trip``) is marked
``@pytest.mark.integration``. It is a scheduled pre-Task-13 gate, not a
Task-12 unit-test-time dependency.
"""

from __future__ import annotations

import inspect
import os

import pytest


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t12-1")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


# Skip the whole module cleanly when agno isn't installed.
agno_client = pytest.importorskip(
    "agno.client",
    reason="agno SDK not installed; contract tests are a no-op until it is.",
)


AGENT_OS_CLIENT = agno_client.AgentOSClient


# ----------------------------------------------------------------------
# Required SDK symbols
# ----------------------------------------------------------------------


_REQUIRED_METHODS = (
    "aget_config",
    "create_session",
    "run_agent",
    "delete_session",
    "get_sessions",
    "aget_agent",
)


@pytest.mark.parametrize("method_name", _REQUIRED_METHODS)
def test_agentos_client_has_required_symbols(method_name: str) -> None:
    """The SDK must expose the methods ``AgentOSRuntime`` depends on."""
    assert hasattr(AGENT_OS_CLIENT, method_name), (
        f"AgentOSClient is missing {method_name!r}; SDK drifted. Pin a compatible "
        f"agno version or update the runtime wrapper."
    )
    attr = getattr(AGENT_OS_CLIENT, method_name)
    assert callable(attr), f"{method_name!r} is not callable."


# ----------------------------------------------------------------------
# Signature shape
# ----------------------------------------------------------------------


def test_run_agent_accepts_kwargs_passthrough() -> None:
    """``output_schema`` is passed through ``run_agent``'s ``**kwargs``.

    Contract note A1 (resolved): the SDK docstring documents this. The
    wrapper depends on the ``**kwargs`` parameter staying open — if the
    SDK ever tightens to an explicit keyword list, we must update.
    """
    sig = inspect.signature(AGENT_OS_CLIENT.run_agent)
    var_keyword = [
        p for p in sig.parameters.values()
        if p.kind is inspect.Parameter.VAR_KEYWORD
    ]
    assert var_keyword, (
        "AgentOSClient.run_agent no longer accepts **kwargs; output_schema "
        "passthrough is broken. Update the wrapper to pass output_schema via "
        "whatever explicit parameter replaced it."
    )


def test_run_agent_required_parameters() -> None:
    """``run_agent`` must still accept ``agent_id``, ``message``, ``session_id``, ``headers``."""
    sig = inspect.signature(AGENT_OS_CLIENT.run_agent)
    names = set(sig.parameters.keys())
    for required in ("agent_id", "message", "session_id", "headers"):
        assert required in names, (
            f"AgentOSClient.run_agent is missing parameter {required!r}; "
            f"wrapper's call shape is broken."
        )


def test_create_session_accepts_agent_id_user_id_session_name() -> None:
    """``create_session`` must accept the call shape the wrapper uses."""
    sig = inspect.signature(AGENT_OS_CLIENT.create_session)
    names = set(sig.parameters.keys())
    for required in ("agent_id", "user_id", "session_name", "headers"):
        assert required in names, (
            f"AgentOSClient.create_session is missing parameter {required!r}."
        )


def test_delete_session_accepts_session_id() -> None:
    """``delete_session`` must accept ``session_id`` + ``headers``."""
    sig = inspect.signature(AGENT_OS_CLIENT.delete_session)
    names = set(sig.parameters.keys())
    for required in ("session_id", "headers"):
        assert required in names, (
            f"AgentOSClient.delete_session is missing parameter {required!r}."
        )


# ----------------------------------------------------------------------
# Response shapes the wrapper consumes
# ----------------------------------------------------------------------


def test_agent_session_detail_schema_has_session_id() -> None:
    """``create_session`` returns a session object with ``.session_id``."""
    from agno.os.schema import AgentSessionDetailSchema

    assert "session_id" in AgentSessionDetailSchema.model_fields, (
        "AgentSessionDetailSchema no longer exposes 'session_id'; wrapper "
        "handle shape breaks."
    )


def test_run_output_has_content() -> None:
    """``run_agent`` returns a RunOutput with ``.content`` (Optional[Any])."""
    from dataclasses import fields

    from agno.run.agent import RunOutput

    field_names = {f.name for f in fields(RunOutput)}
    assert "content" in field_names, (
        "RunOutput no longer has 'content'; wrapper's parse boundary breaks."
    )


# ----------------------------------------------------------------------
# Constructor
# ----------------------------------------------------------------------


def test_agent_os_client_constructor_takes_base_url() -> None:
    """Constructor signature lock — ``base_url`` is the construction parameter."""
    sig = inspect.signature(AGENT_OS_CLIENT.__init__)
    names = set(sig.parameters.keys())
    assert "base_url" in names, (
        "AgentOSClient constructor no longer accepts 'base_url'; wrapper "
        "construction is broken."
    )


# ----------------------------------------------------------------------
# Live dry-run — placeholder only, skipped by default
# ----------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skip(
    reason=(
        "Pre-Task-13 gate. Requires a live AgentOS instance with a "
        "pre-registered test agent. Not part of Task 12 unit-test cycle."
    )
)
def test_live_agentos_round_trip() -> None:  # pragma: no cover — placeholder
    """Placeholder for the pre-Task-13 integration check.

    When Task 13 reaches the deploy-saga integration gate, stand up a
    throwaway AgentOS with one test agent and exercise:

        client = AgentOSClient(base_url=...)
        session = await client.create_session(agent_id="test", user_id="u")
        result = await client.run_agent(agent_id="test", message="ping",
                                         session_id=session.session_id,
                                         output_schema=<AgentAction schema>)
        await client.delete_session(session_id=session.session_id)

    Confirm the structured-output branch taken by the real SDK (dict vs
    JSON-encoded string in ``result.content``) and record it in the
    contract note under A1.
    """
    assert False, "Integration placeholder — should not run in unit-test mode."
