"""Plan §Task 4 regression-lock target — agentos_app re-exports backend SoT seeds
verbatim (object identity, not copy).

Currently locks the SWAP_EXECUTOR_V1_SEED re-export. When Task 4 lands the
rebalance multi-seed surface, this file gains a sibling test for
REBALANCE_EXECUTOR_V1_SEED.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `agentos_app` (sibling of backend/) importable for this regression-lock test.
# Mirrors agentos_app/canonical_template_contract.py's _ensure_backend_on_path()
# in the reverse direction — the project intentionally keeps these two packages
# importable from each other via runtime sys.path manipulation rather than
# polluting either side's pyproject.toml.
_AGENT_RANK_ROOT = Path(__file__).resolve().parents[2]   # tests/ → backend/ → agent-rank/
if str(_AGENT_RANK_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_RANK_ROOT))


def test_agentos_app_swap_seed_is_same_object_as_backend_seed():
    """Object identity, not deep equality — the agentos_app re-export must
    point at the backend's SWAP_EXECUTOR_V1_SEED dict, never at a copy.

    If this fails, agentos_app is forking the seed (a forbidden duplicate
    source of truth per spec §5.3 / plan §Task 4 / canonical_template_contract.py
    docstring).
    """
    from src.services.template_service import (
        SWAP_EXECUTOR_V1_SEED as backend_swap_seed,
    )
    from agentos_app.canonical_template_contract import (
        SWAP_EXECUTOR_V1_SEED as agentos_swap_seed,
    )
    assert agentos_swap_seed is backend_swap_seed, (
        "agentos_app must re-export the backend SWAP_EXECUTOR_V1_SEED by reference, "
        "not a copy. A copy would let the agentos_app and backend drift independently "
        "— exactly the bug canonical_template_contract.py was created to prevent."
    )
