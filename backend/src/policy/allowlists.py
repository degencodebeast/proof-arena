"""V2 wallet-policy allowlist profiles.

Single source of truth for the Orca devnet program allowlist derived in
Phase 0 (``V0-VAL-2``). Other profiles (e.g. a test substitute, a later
mainnet profile) are loaded through ``load_allowlist_profile`` so the
policy engine can remain provider-agnostic and not hardcode any specific
program footprint.

See ``PHASE_0_CLOSEOUT_NOTE.md`` §V0-VAL-2 for the derivation evidence:
the six program IDs below are the observed instruction footprint of a
real SOL → devUSDC swap on devnet (tx
``266Lc9oNy9fPDnSAVdUMFQfeUjWSHyiciXQSPT3Mb5PrRQQ82GKKc6NDb71WM3rSUmbSTS9hrTf4hWYAMc2AjCqU``
at slot 456581764).
"""

from __future__ import annotations

import copy
import json
from typing import Any


# ---------------------------------------------------------------------------
# Phase 0-locked Orca devnet allowlist
# ---------------------------------------------------------------------------

# Intentional order — kept stable for byte-level comparisons in tests and
# any future golden-output assertions downstream. Comments attribute each
# program to its role in a real Orca swap footprint.
ORCA_DEVNET_ALLOWLIST: dict[str, Any] = {
    "programs": [
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",   # Orca Whirlpools v2
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",   # SPL Token
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",  # Associated Token Account
        "11111111111111111111111111111111",              # System Program
        "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",   # Memo (Orca SDK emits)
        "ComputeBudget111111111111111111111111111111",   # Compute Budget
    ],
}


def load_allowlist_profile(path: str | None = None) -> dict[str, Any]:
    """Return a deep copy of an allowlist profile.

    - ``path is None`` → deep copy of ``ORCA_DEVNET_ALLOWLIST`` (Phase-0 default).
    - ``path`` → read JSON from disk and return the parsed dict.

    Deep-copying the default prevents a caller's mutation from poisoning
    later callers. Errors surface as ``PolicyEngineError`` so callers have
    a single exception type to trap across engine + profile I/O.
    """
    # Late import: a Phase P0 "side-effect-free" test pops
    # ``src.policy.engine`` from ``sys.modules`` and re-imports it, which
    # would make a module-level ``PolicyEngineError`` reference stale
    # relative to callers' fresh imports. Resolving at call time keeps the
    # class identity consistent with whatever's currently in sys.modules.
    from src.policy.engine import PolicyEngineError

    if path is None:
        return copy.deepcopy(ORCA_DEVNET_ALLOWLIST)

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as e:
        raise PolicyEngineError(
            f"load_allowlist_profile: file not found: {path!r}"
        ) from e
    except json.JSONDecodeError as e:
        raise PolicyEngineError(
            f"load_allowlist_profile: malformed JSON in {path!r}: {e}"
        ) from e

    if not isinstance(data, dict):
        raise PolicyEngineError(
            f"load_allowlist_profile: expected JSON object at top level in {path!r}, "
            f"got {type(data).__name__}"
        )
    return data
