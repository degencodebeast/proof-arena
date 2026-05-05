"""Single-source-of-truth re-exporter for ``SWAP_EXECUTOR_V1_SEED``.

The canonical V2 template behavior contract lives at
``backend/src/services/template_service.py:63-89`` (Task A2). The
AgentOS service imports it from there verbatim — never forks /
vendors a copy. Object-identity equality is asserted by
``tests/test_seed_is_single_source_of_truth.py``.

Path resolution:
- In production (Docker), the backend ``src/`` tree is copied to
  ``/app/backend_src/`` and ``PYTHONPATH`` includes it. The plain
  ``from src.services.template_service import SWAP_EXECUTOR_V1_SEED``
  import succeeds.
- In local dev / pytest, this module appends the sibling
  ``../backend/`` directory to ``sys.path`` so the same import
  resolves against the in-tree backend.

Either way the SoT is one Python object; agentos_app does not maintain
a parallel copy.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _ensure_backend_on_path() -> None:
    """Make ``backend/src`` (and `backend/`) importable as ``src.*``.

    Idempotent — re-runs are no-ops once the path is present.
    """
    here = Path(__file__).resolve()
    # `agent-rank/agentos_app/canonical_template_contract.py` →
    # `agent-rank/`, then `agent-rank/backend/`.
    backend_dir = here.parent.parent / "backend"
    if backend_dir.is_dir():
        backend_str = str(backend_dir)
        if backend_str not in sys.path:
            sys.path.insert(0, backend_str)


_ensure_backend_on_path()

# Re-export — DO NOT redefine. If this import fails, fix the path /
# Dockerfile, never inline a vendored copy of the dict.
from src.services.template_service import (  # noqa: E402 — sys.path mutation must precede this
    SWAP_EXECUTOR_V1_SEED as SWAP_EXECUTOR_V1_SEED,
    REBALANCE_EXECUTOR_V1_SEED as REBALANCE_EXECUTOR_V1_SEED,
)


def canonical_system_prompt() -> str:
    """Return the canonical system prompt for the V2 swap executor.

    Wrapper exists so callers depend on the function (stable surface)
    rather than reaching into the dict directly. The function returns
    the same object the SoT dict holds — no copy.
    """
    prompt = SWAP_EXECUTOR_V1_SEED["system_prompt"]
    if not isinstance(prompt, str) or not prompt:
        raise RuntimeError(
            "SWAP_EXECUTOR_V1_SEED['system_prompt'] must be a non-empty string"
        )
    return prompt


def canonical_template_key() -> str:
    """Return the canonical template_key (also the recommended agent id)."""
    return SWAP_EXECUTOR_V1_SEED["template_key"]


def canonical_seeds() -> dict[str, dict]:
    """Return both canonical seeds keyed by template_key.

    Object-identity to backend SoT preserved — never copied / forked.
    Each value `is` the corresponding seed dict in
    ``src.services.template_service``; the agentos_app surface is a
    re-export, not a parallel definition.
    """
    return {
        "swap_executor_v1":      SWAP_EXECUTOR_V1_SEED,
        "rebalance_executor_v1": REBALANCE_EXECUTOR_V1_SEED,
    }


def canonical_template_keys() -> list[str]:
    """List both canonical template keys (sorted)."""
    return sorted(["swap_executor_v1", "rebalance_executor_v1"])


__all__: list[str] = [
    "SWAP_EXECUTOR_V1_SEED",
    "REBALANCE_EXECUTOR_V1_SEED",
    "canonical_seeds",
    "canonical_template_keys",
    "canonical_template_key",
    "canonical_system_prompt",
]
