"""Spec §10 test 17 — ActionValidator gains allowed_action_types injection."""
from __future__ import annotations

import pytest

from src.db.schemas import AgentActionType
from src.integrity.action_validator import ActionValidator


class _StubSwapService:
    def is_quote_fresh(self, qid, max_age): return True
    def get_cached_quote(self, qid): return None


@pytest.mark.asyncio
async def test_default_allowed_action_types_unchanged():
    """Regression-lock: omitting allowed_action_types preserves the V1 behavior."""
    v = ActionValidator(_StubSwapService(), {})
    assert v.allowed_actions == {
        AgentActionType.EXECUTE_SWAP,
        AgentActionType.WAIT,
        AgentActionType.FINISH,
    }


@pytest.mark.asyncio
async def test_rebalance_allowed_action_types_rejects_execute_swap():
    v = ActionValidator(
        _StubSwapService(), {},
        allowed_action_types={AgentActionType.FINISH, AgentActionType.WAIT},
    )
    result = await v.validate(
        {"type": "EXECUTE_SWAP", "params": {"quote_id": "x", "max_slippage_bps": 10}},
        state={},
    )
    assert result.valid is False
    assert "not allowed" in result.reason.lower()


@pytest.mark.asyncio
async def test_rebalance_allowed_action_types_accepts_finish():
    v = ActionValidator(
        _StubSwapService(), {},
        allowed_action_types={AgentActionType.FINISH, AgentActionType.WAIT},
    )
    result = await v.validate({"type": "FINISH", "params": {}}, state={})
    assert result.valid is True
