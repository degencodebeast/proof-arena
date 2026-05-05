"""Spec §10 test 19 — update_instance_config produces a new versioned row for rebalance.

Regression-lock: update_instance_config is template-agnostic and reuses
deploy_instance, which after Task 16 is template-aware. A rebalance update
must flow through validate_spec_for_template and produce a new versioned row
without mutating the old row.

No production code change is permitted in this task. If the test fails on
first run, halt and reopen the analysis per the regression-lock gate.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from src.db.models import AgentInstance, AgentTemplate
from src.policy.engine import InstancePolicyEngine
from src.services.instance_service import InstanceDeployError, InstanceService
from src.services.template_service import (
    REBALANCE_EXECUTOR_V1_SEED,
    TemplateService,
)
from tests._rebalance_helpers import make_rebalance_envelope


@pytest.mark.asyncio
async def test_rebalance_update_instance_config_creates_new_versioned_instance(
    db, monkeypatch
):
    # Setup a deployed rebalance instance via the saga.
    await TemplateService(db).register_template(**REBALANCE_EXECUTOR_V1_SEED)
    from unittest.mock import AsyncMock
    from src.runtime.base import InstanceHandle
    wallet_service = AsyncMock()
    wallet_service.create_hosted_wallet.return_value = {
        "id": "priv-x", "address": "Wx",
    }
    runtime = AsyncMock()
    runtime.deploy.return_value = InstanceHandle(instance_id="rebalance_executor_v1", extra={})

    svc = InstanceService(
        db=db, policy_engine=InstancePolicyEngine(),
        wallet_service=wallet_service, runtime=runtime,
        hosted_wallet_policy_id="phase0", authorization_pubkey="base64",
    )
    consent = {
        "devnet_only_acknowledged": True,
        "platform_managed_signing_acknowledged": True,
        "spend_caps_acknowledged": True,
        "no_indemnity_acknowledged": True,
    }

    old_envelope = make_rebalance_envelope()
    old = await svc.deploy_instance(
        template_key="rebalance_executor_v1",
        effective_config=old_envelope,
        consent=consent,
        owner_ref="instance:owner-A",
    )
    assert old.status == "live"
    assert old.superseded_by_instance_id is None

    # Update with a NEW envelope (different threshold).
    new_envelope = make_rebalance_envelope(rebalance_threshold_bps=200)

    new = await svc.update_instance_config(
        instance_id=old.instance_id,
        new_config=new_envelope,
        consent=consent,
    )
    # (a) new row exists with new envelope
    assert new.instance_id != old.instance_id
    assert new.template_id == old.template_id
    assert json.loads(new.effective_config_json)["rebalance_threshold_bps"] == 200

    # (b) old row's superseded_by_instance_id points at new
    refreshed_old = (
        await db.execute(
            select(AgentInstance).where(AgentInstance.instance_id == old.instance_id)
        )
    ).scalar_one()
    assert refreshed_old.superseded_by_instance_id == new.instance_id

    # (c) old row config NOT mutated in place
    assert json.loads(refreshed_old.effective_config_json)["rebalance_threshold_bps"] == \
        old_envelope["rebalance_threshold_bps"]

    # (d) new row's template_key is rebalance_executor_v1 — went through
    #     validate_spec_for_template, not the swap path.
    template = (
        await db.execute(
            select(AgentTemplate).where(AgentTemplate.template_id == new.template_id)
        )
    ).scalar_one()
    assert template.template_key == "rebalance_executor_v1"


@pytest.mark.asyncio
async def test_rebalance_update_with_invalid_envelope_keeps_old_row_intact(db):
    """Sad-path: invalid envelope must NOT supersede the old row.

    Spec §10 test 19 sad-path lock — passing an envelope that fails
    validate_spec_for_template("rebalance_executor_v1", ...) produces no new
    row and raises a clear typed error; the old row is unchanged.
    """
    await TemplateService(db).register_template(**REBALANCE_EXECUTOR_V1_SEED)
    from unittest.mock import AsyncMock
    from src.runtime.base import InstanceHandle
    wallet_service = AsyncMock()
    wallet_service.create_hosted_wallet.return_value = {"id": "priv-x", "address": "Wx"}
    runtime = AsyncMock()
    runtime.deploy.return_value = InstanceHandle(instance_id="rebalance_executor_v1", extra={})
    svc = InstanceService(
        db=db, policy_engine=InstancePolicyEngine(),
        wallet_service=wallet_service, runtime=runtime,
        hosted_wallet_policy_id="phase0", authorization_pubkey="base64",
    )
    consent = {
        "devnet_only_acknowledged": True,
        "platform_managed_signing_acknowledged": True,
        "spend_caps_acknowledged": True,
        "no_indemnity_acknowledged": True,
    }
    old_envelope = make_rebalance_envelope()
    old = await svc.deploy_instance(
        template_key="rebalance_executor_v1",
        effective_config=old_envelope, consent=consent,
        owner_ref="instance:owner-A",
    )
    assert old.status == "live"
    assert old.superseded_by_instance_id is None

    pre_count = (
        await db.execute(select(AgentInstance).where(
            AgentInstance.template_id == old.template_id
        ))
    ).scalars().all()

    # Invalid envelope: rebalance_threshold_bps below the locked [1, 5000] range.
    bad_envelope = make_rebalance_envelope(rebalance_threshold_bps=0)

    with pytest.raises(InstanceDeployError):
        await svc.update_instance_config(
            instance_id=old.instance_id,
            new_config=bad_envelope,
            consent=consent,
        )

    # (a) No new live replacement row was created.
    post_count = (
        await db.execute(select(AgentInstance).where(
            AgentInstance.template_id == old.template_id
        ))
    ).scalars().all()
    assert len(post_count) == len(pre_count), (
        "Spec §10 test 19 sad-path: invalid envelope created a new agent_instances row"
    )

    # (b) Old row's superseded_by_instance_id is still None — no supersession.
    refreshed_old = (
        await db.execute(
            select(AgentInstance).where(AgentInstance.instance_id == old.instance_id)
        )
    ).scalar_one()
    assert refreshed_old.superseded_by_instance_id is None, (
        "Spec §10 test 19 sad-path: old row was incorrectly superseded by a failed update"
    )

    # (c) Old row's effective_config_json is unchanged.
    assert json.loads(refreshed_old.effective_config_json) == old_envelope, (
        "Spec §10 test 19 sad-path: old row's effective_config_json was mutated in place"
    )

    # (d) Old row's status is still 'live'.
    assert refreshed_old.status == "live", (
        "Spec §10 test 19 sad-path: old row's status drifted away from 'live'"
    )
