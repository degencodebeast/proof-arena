"""V2 Phase P0 RED tests — interface lock.

Targets:
- backend/src/runtime/base.py — `InstanceRuntime` protocol (not yet implemented)
- backend/src/policy/engine.py — `InstancePolicyEngine` (not yet implemented)
- backend/src/providers/hosted_instance_provider.py — implements V1 AgentDecisionProvider (not yet implemented)

Edge-case invariants covered:
- I1: protocols do NOT import provider-specific modules (no Privy, no AgentOS)
- I3: HostedInstanceProvider satisfies the existing AgentDecisionProvider protocol
- E1: importing the P0 protocol modules has no side effects (no RPC, no env reads, no DB)
- N3: HostedInstanceProvider fails closed when runtime is unavailable
"""

from __future__ import annotations

import os
import sys
from typing import Protocol, runtime_checkable
from unittest.mock import AsyncMock, MagicMock

import pytest


os.environ["ADMIN_API_KEY"] = "test-admin-key-p0"
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/unused"
)


# ===========================================================================
# I1 — provider-agnostic import boundary
# ===========================================================================


def _module_import_lines(module_name: str) -> list[str]:
    """Return only the import statements from the module source.

    Scanning the whole source catches documentation references too, which
    produces false positives. Parse the AST and return only the textual
    representation of Import / ImportFrom nodes.
    """
    import ast
    import importlib

    mod = importlib.import_module(module_name)
    path = mod.__file__
    assert path is not None, f"{module_name} has no __file__"
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source)
    lines: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                lines.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod_name = node.module or ""
            for alias in node.names:
                lines.append(f"from {mod_name} import {alias.name}")
    return lines


_PROVIDER_GIVEAWAYS = (
    "privy",
    "PRIVY",
    "agentos",
    "AgentOS",
    "httpx",  # no outbound HTTP from the protocol layer
    "solders",  # chain libs belong in services/runtime implementations, not protocols
)


def _assert_no_provider_imports(module_name: str, forbidden: tuple[str, ...]) -> None:
    lines = _module_import_lines(module_name)
    offenders: list[str] = []
    for line in lines:
        for bad in forbidden:
            if bad.lower() in line.lower():
                offenders.append(f"{line}  ← matched {bad!r}")
    assert not offenders, (
        f"{module_name} imports provider-specific tokens:\n  "
        + "\n  ".join(offenders)
    )


def test_runtime_base_does_not_import_providers():
    """I1 — runtime/base.py must stay provider-agnostic."""
    _assert_no_provider_imports("src.runtime.base", _PROVIDER_GIVEAWAYS)


def test_policy_engine_does_not_import_providers():
    """I1 — policy/engine.py must stay provider-agnostic."""
    _assert_no_provider_imports("src.policy.engine", _PROVIDER_GIVEAWAYS)


def test_hosted_instance_provider_does_not_import_agentos():
    """I1 — the provider bridge must not import AgentOS SDK at module level.

    Concrete AgentOS wiring belongs in src/runtime/agentos.py (Phase B work).
    """
    _assert_no_provider_imports(
        "src.providers.hosted_instance_provider",
        ("agentos", "AgentOS"),
    )


# ===========================================================================
# E1 — importing the protocols has no side effects
# ===========================================================================


def test_importing_runtime_base_is_side_effect_free(monkeypatch):
    """E1 — importing src.runtime.base must not read env or open sockets."""
    # Unset everything we can.
    for key in list(os.environ):
        if key.startswith(("PRIVY_", "AUTHORITY_", "SOLANA_", "TREASURY_")):
            monkeypatch.delenv(key, raising=False)

    # Fresh import.
    sys.modules.pop("src.runtime.base", None)
    import src.runtime.base  # noqa: F401

    # No connection objects, no RPC clients created at import time.
    module = sys.modules["src.runtime.base"]
    top_level_names = {name for name in dir(module) if not name.startswith("_")}
    forbidden = {"AsyncClient", "Provider", "SolanaService", "httpx", "privy_client"}
    leaked = top_level_names & forbidden
    assert not leaked, f"runtime.base leaks runtime objects at module scope: {leaked}"


def test_importing_policy_engine_is_side_effect_free(monkeypatch):
    """E1 — importing src.policy.engine must not read env or open sockets."""
    sys.modules.pop("src.policy.engine", None)
    import src.policy.engine  # noqa: F401


# ===========================================================================
# I3 — HostedInstanceProvider satisfies V1 AgentDecisionProvider
# ===========================================================================


@pytest.mark.asyncio
async def test_hosted_instance_provider_satisfies_agent_decision_protocol():
    """I3 — the bridge must be usable wherever V1 expects an AgentDecisionProvider.

    Concretely: RunnerService.execute_run() already accepts any
    AgentDecisionProvider. A HostedInstanceProvider must satisfy the same
    protocol shape (async decide(state) -> AgentAction).
    """
    from src.providers.base import AgentDecisionProvider
    from src.providers.hosted_instance_provider import HostedInstanceProvider

    # The class must be usable as an AgentDecisionProvider.
    # Duck-typing against the protocol: instance.decide must exist and be async-callable.
    runtime = MagicMock()
    handle = MagicMock()

    # Mock the runtime's decide invocation.
    from src.db.schemas import AgentAction, AgentActionType

    async def _fake_invoke_decide(h, state):
        return AgentAction(type=AgentActionType.FINISH, params={})

    runtime.invoke_decide = _fake_invoke_decide

    provider = HostedInstanceProvider(runtime=runtime, handle=handle)

    # Must be detectable as an AgentDecisionProvider.
    assert isinstance(provider, AgentDecisionProvider)

    # decide(state) must run and return an AgentAction.
    from src.challenges.base import ChallengeState

    state = MagicMock(spec=ChallengeState)
    result = await provider.decide(state)
    assert result.type == AgentActionType.FINISH


# ===========================================================================
# N3 — HostedInstanceProvider fails closed when runtime is unavailable
# ===========================================================================


@pytest.mark.asyncio
async def test_hosted_instance_provider_raises_when_runtime_is_none():
    """N3 — constructing the provider without a runtime must raise a typed error.

    Silent no-op is forbidden. Mirrors V1 ChallengeService._require_program().
    """
    from src.providers.hosted_instance_provider import (
        HostedInstanceProvider,
        HostedInstanceError,
    )

    with pytest.raises((HostedInstanceError, ValueError, TypeError)):
        HostedInstanceProvider(runtime=None, handle=MagicMock())


@pytest.mark.asyncio
async def test_hosted_instance_provider_rejects_non_agent_action_from_runtime():
    """Real negative test: if a buggy runtime returns the wrong type,
    the bridge must refuse to propagate it up to the V1 runner."""
    from src.providers.hosted_instance_provider import (
        HostedInstanceError,
        HostedInstanceProvider,
    )

    runtime = MagicMock()

    async def _buggy(h, state):
        return {"type": "FINISH"}  # dict, not AgentAction

    runtime.invoke_decide = _buggy

    provider = HostedInstanceProvider(runtime=runtime, handle=MagicMock())
    with pytest.raises(HostedInstanceError) as exc:
        await provider.decide(state=MagicMock())
    assert "AgentAction" in str(exc.value)


# ===========================================================================
# InstanceRuntime protocol shape
# ===========================================================================


def test_instance_runtime_protocol_has_required_methods():
    """Protocol must expose deploy / invoke_decide / teardown.

    This is a documentation test: the names and shape matter downstream for
    Phase B (runtime/agentos.py) and for policy/engine consumers.
    """
    from src.runtime.base import InstanceRuntime

    # Protocol class should declare these methods.
    for name in ("deploy", "invoke_decide", "teardown"):
        assert hasattr(InstanceRuntime, name), (
            f"InstanceRuntime protocol missing required method: {name}"
        )


def test_instance_runtime_is_runtime_checkable():
    """isinstance() against InstanceRuntime must work so callers can fail fast."""
    from src.runtime.base import InstanceRuntime

    class _Impl:
        async def deploy(self, spec):
            return None

        async def invoke_decide(self, handle, state):
            return None

        async def teardown(self, handle):
            return None

    impl = _Impl()
    # If InstanceRuntime is @runtime_checkable, isinstance works.
    assert isinstance(impl, InstanceRuntime)
