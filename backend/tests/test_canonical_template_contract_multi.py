"""Spec §10 test 4 (partial) — agentos_app exposes both canonical seeds (Task 4)."""
from __future__ import annotations

import sys
from pathlib import Path

# Make `agentos_app` (sibling of backend/) importable for this test.
# Mirrors agentos_app/canonical_template_contract.py's _ensure_backend_on_path()
# in the reverse direction — see test_seed_is_single_source_of_truth.py for
# the established pattern.
_AGENT_RANK_ROOT = Path(__file__).resolve().parents[2]
if str(_AGENT_RANK_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_RANK_ROOT))


def test_canonical_seeds_returns_two_keys_with_object_identity():
    """Object identity (NOT deep equality) — agentos_app re-exports the
    backend SoT seed dicts by reference, never via dict() copy."""
    from agentos_app.canonical_template_contract import (
        canonical_seeds,
        SWAP_EXECUTOR_V1_SEED,
        REBALANCE_EXECUTOR_V1_SEED,
    )
    from src.services.template_service import (
        SWAP_EXECUTOR_V1_SEED as SWAP_SOT,
        REBALANCE_EXECUTOR_V1_SEED as REBAL_SOT,
    )
    seeds = canonical_seeds()
    assert set(seeds.keys()) == {"swap_executor_v1", "rebalance_executor_v1"}
    # Object identity at both layers: re-export AND backend SoT.
    assert seeds["swap_executor_v1"] is SWAP_EXECUTOR_V1_SEED is SWAP_SOT
    assert seeds["rebalance_executor_v1"] is REBALANCE_EXECUTOR_V1_SEED is REBAL_SOT


def test_canonical_template_keys_returns_both_sorted():
    from agentos_app.canonical_template_contract import canonical_template_keys
    keys = canonical_template_keys()
    assert sorted(keys) == ["rebalance_executor_v1", "swap_executor_v1"]


def test_singular_helpers_remain_swap_only_shims():
    """Existing test_seed_is_single_source_of_truth.py + any caller that uses
    the singular helpers must keep working unchanged."""
    from agentos_app.canonical_template_contract import (
        canonical_template_key,
        canonical_system_prompt,
    )
    from src.services.template_service import SWAP_EXECUTOR_V1_SEED
    assert canonical_template_key() == "swap_executor_v1"
    # Object identity to the swap seed's system_prompt entry, not just equal.
    assert canonical_system_prompt() is SWAP_EXECUTOR_V1_SEED["system_prompt"]
