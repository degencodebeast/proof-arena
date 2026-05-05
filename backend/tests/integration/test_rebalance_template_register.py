"""Spec §10 test 3 — register REBALANCE_EXECUTOR_V1_SEED through TemplateService (Task 3)."""
from __future__ import annotations

import json
import pytest

from src.db.models import AgentTemplate
from src.services.template_service import (
    REBALANCE_EXECUTOR_V1_SEED,
    SWAP_EXECUTOR_V1_SEED,
    TemplateService,
    TemplateValidationError,
)


def _seed_register_kwargs(seed: dict) -> dict:
    """Helper: convert a seed dict into register_template kwargs.

    `register_template` takes individual kwargs; the seed is a dict shape
    that maps directly when unpacked. `is_deployable` is bool-typed in the
    seed; `register_template` accepts it via its kwarg signature.
    """
    return {
        "template_key": seed["template_key"],
        "template_version": seed["template_version"],
        "description": seed["description"],
        "allowed_fields_json": seed["allowed_fields_json"],
        "default_config_json": seed["default_config_json"],
        "system_prompt": seed["system_prompt"],
        "is_deployable": seed["is_deployable"],
    }


@pytest.mark.asyncio
async def test_register_rebalance_template_succeeds(db):
    """INV-13: register_template(REBALANCE_EXECUTOR_V1_SEED) end-to-end."""
    svc = TemplateService(db)
    template = await svc.register_template(**_seed_register_kwargs(REBALANCE_EXECUTOR_V1_SEED))
    assert template.template_key == "rebalance_executor_v1"
    assert template.is_deployable in (True, 1)
    fields = json.loads(template.allowed_fields_json)
    assert sorted(fields) == sorted([
        "allowed_token_universe", "target_allocations", "rebalance_threshold_bps",
        "max_slippage_bps", "max_position_weight", "max_trade_value", "dry_run",
    ])


@pytest.mark.asyncio
async def test_register_rebalance_template_with_swap_fields_rejected(db):
    """INV-14: rebalance template with swap-shaped allowed_fields_json fails registration."""
    svc = TemplateService(db)
    bad_seed = dict(REBALANCE_EXECUTOR_V1_SEED)
    bad_seed["allowed_fields_json"] = json.dumps(sorted([
        "allowed_token_universe", "max_slippage_bps", "max_position_size",
        "max_iterations", "max_runtime_seconds",
    ]))  # swap fields under rebalance template_key
    with pytest.raises(TemplateValidationError):
        await svc.register_template(**_seed_register_kwargs(bad_seed))


@pytest.mark.asyncio
async def test_register_swap_template_still_succeeds(db):
    """INV-15: regression-lock — swap registration unchanged."""
    svc = TemplateService(db)
    template = await svc.register_template(**_seed_register_kwargs(SWAP_EXECUTOR_V1_SEED))
    assert template.template_key == "swap_executor_v1"
