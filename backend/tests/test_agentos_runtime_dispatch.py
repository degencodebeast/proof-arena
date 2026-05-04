"""Spec §5.3 + plan Task 7 — AgentOSRuntime dispatches canonical_agent_id by template_key."""
from __future__ import annotations

import sys
from pathlib import Path

# Make `agentos_app` (sibling of backend/) importable for any cross-package usage.
_AGENT_RANK_ROOT = Path(__file__).resolve().parents[2]
if str(_AGENT_RANK_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_RANK_ROOT))

import os
import pytest

os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-dispatch")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)

pytest.importorskip(
    "agno.client",
    reason="agno SDK not installed; runtime tests require it.",
)

from src.runtime.agentos import AgentOSRuntime, AgentOSRuntimeError
from src.runtime.base import InstanceSpec


def _spec(template_key: str) -> InstanceSpec:
    return InstanceSpec(
        template_key=template_key,
        template_version=template_key,
        effective_config={},
        instance_owner_ref="instance:0",
    )


def test_constructor_requires_non_empty_canonical_agent_ids_dict():
    """Plan §Task 7: empty dict raises ValueError with a clear message."""
    with pytest.raises(ValueError):
        AgentOSRuntime(api_url="http://localhost:8000", canonical_agent_ids={})


def test_constructor_requires_at_least_one_canonical_agent_id_source():
    """If neither canonical_agent_ids nor legacy canonical_agent_id is set, raise."""
    with pytest.raises(ValueError):
        AgentOSRuntime(api_url="http://localhost:8000")


def test_constructor_accepts_dict_of_template_keys():
    rt = AgentOSRuntime(
        api_url="http://localhost:8000",
        canonical_agent_ids={
            "swap_executor_v1": "swap-agent-id",
            "rebalance_executor_v1": "rebalance-agent-id",
        },
    )
    assert rt._canonical_agent_ids["swap_executor_v1"] == "swap-agent-id"
    assert rt._canonical_agent_ids["rebalance_executor_v1"] == "rebalance-agent-id"


def test_constructor_legacy_singular_param_is_back_compat():
    """Plan §Task 7 back-compat: legacy `canonical_agent_id` string still works
    and is internally promoted to a {swap: id} dict."""
    rt = AgentOSRuntime(
        api_url="http://localhost:8000",
        canonical_agent_id="legacy-swap-id",
    )
    # Legacy callers see exactly one entry, keyed by the swap template_key.
    assert rt._canonical_agent_ids == {"swap_executor_v1": "legacy-swap-id"}


@pytest.mark.asyncio
async def test_deploy_unknown_template_key_raises_runtime_error():
    """Plan §Task 7: deploy() with an unrecognized template_key raises
    AgentOSRuntimeError mentioning the missing key and the covered set."""
    rt = AgentOSRuntime(
        api_url="http://localhost:8000",
        canonical_agent_ids={"swap_executor_v1": "swap-agent-id"},
    )
    with pytest.raises(AgentOSRuntimeError) as exc:
        await rt.deploy(_spec("rebalance_executor_v1"))
    assert "rebalance_executor_v1" in str(exc.value)
    assert "swap_executor_v1" in str(exc.value)  # covered set listed
