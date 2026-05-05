"""Task 22 — Structural regression-lock tests for cats.py single-module invariant.

Spec §10 test 16: the rebalance_policy route must live in the existing single-file
cats.py, NOT in a cats/ package.

These four tests assert file-system and source-text shape only. They do NOT hit the
database or the HTTP stack. They are expected to pass before the route handler is
written (regression-lock), EXCEPT test 3 which will go RED until the route handler
is added.
"""
from __future__ import annotations

import pathlib

import pytest

pytestmark = pytest.mark.integration

# Repo-relative backend root. Locate it relative to this test file.
_BACKEND = pathlib.Path(__file__).parent.parent.parent  # .../backend/
_API_DIR = _BACKEND / "src" / "api"


def test_rebalance_policy_module_file_does_not_exist():
    """kill-12: src/api/cats/rebalance_policy.py must NOT exist.

    If this file appears it means someone created a cats/ package instead of
    adding the route to the single cats.py module.
    """
    bad_path = _API_DIR / "cats" / "rebalance_policy.py"
    assert not bad_path.exists(), (
        f"Found {bad_path} — cats/ package must NOT be created (kill-12). "
        "Add the route to the existing cats.py single-file module."
    )


def test_cats_module_is_single_file():
    """cats.py must exist as a file; src/api/cats/ directory must NOT exist."""
    single_file = _API_DIR / "cats.py"
    package_dir = _API_DIR / "cats"

    assert single_file.is_file(), (
        f"{single_file} does not exist — cats module must be a single file."
    )
    assert not package_dir.is_dir(), (
        f"{package_dir} directory exists — cats must remain a single-file module, "
        "not a package."
    )


def test_cats_module_contains_rebalance_route_handler():
    """cats.py source must contain the rebalance_policy route path string."""
    cats_source = (_API_DIR / "cats.py").read_text(encoding="utf-8")
    assert '"/rebalance_policy/{run_id}"' in cats_source, (
        'cats.py does not contain the route path "/rebalance_policy/{run_id}". '
        "The route handler has not been added yet."
    )


def test_router_registers_one_cats_router():
    """router.py must mention cats_router at most 3 times (import + include + tag).

    Guards against accidental duplication (e.g., a second cats sub-router being
    imported and included separately).
    """
    router_source = (_API_DIR / "router.py").read_text(encoding="utf-8")
    occurrences = router_source.count("cats_router")
    assert occurrences <= 3, (
        f"router.py mentions 'cats_router' {occurrences} times (expected ≤ 3). "
        "Check for accidental duplicate imports or includes."
    )
    # Must appear at least once (it IS registered).
    assert occurrences >= 1, "router.py does not mention cats_router at all."
