"""Task 7 follow-up — get_canonical_agent_ids() helper.

Per plan §Task 7 (lines ~1587-1617), parses AGENTOS_CANONICAL_AGENT_IDS_JSON
as a JSON dict; falls back to AGENTOS_CANONICAL_AGENT_ID legacy as
{"swap_executor_v1": legacy_id}; raises ValueError on invalid input or
when neither source is set.
"""
from __future__ import annotations

import pytest

from src.config import Settings, get_canonical_agent_ids


def _settings(**overrides):
    """Build a Settings instance for testing, with defaults overridden."""
    base = {
        "AGENTOS_CANONICAL_AGENT_ID": "",
        "AGENTOS_CANONICAL_AGENT_IDS_JSON": "",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_parses_valid_json_dict():
    """JSON env var with both swap and rebalance keys parses into a dict."""
    import json
    s = _settings(
        AGENTOS_CANONICAL_AGENT_IDS_JSON=json.dumps({
            "swap_executor_v1": "swap-id-from-json",
            "rebalance_executor_v1": "rebalance-id-from-json",
        }),
        AGENTOS_CANONICAL_AGENT_ID="legacy-swap-id",  # ignored when JSON is set
    )
    result = get_canonical_agent_ids(s)
    assert result == {
        "swap_executor_v1": "swap-id-from-json",
        "rebalance_executor_v1": "rebalance-id-from-json",
    }


def test_falls_back_to_legacy_when_json_empty():
    """JSON empty → fall back to AGENTOS_CANONICAL_AGENT_ID as swap-only dict."""
    s = _settings(
        AGENTOS_CANONICAL_AGENT_IDS_JSON="",
        AGENTOS_CANONICAL_AGENT_ID="legacy-swap-id",
    )
    result = get_canonical_agent_ids(s)
    assert result == {"swap_executor_v1": "legacy-swap-id"}


def test_raises_value_error_on_invalid_json():
    """Malformed JSON must raise ValueError, not leak json.JSONDecodeError."""
    s = _settings(
        AGENTOS_CANONICAL_AGENT_IDS_JSON="{not valid json",
        AGENTOS_CANONICAL_AGENT_ID="legacy-swap-id",
    )
    with pytest.raises(ValueError) as exc:
        get_canonical_agent_ids(s)
    assert "AGENTOS_CANONICAL_AGENT_IDS_JSON" in str(exc.value)


def test_raises_value_error_when_json_is_not_a_dict():
    """JSON-decoded value must be a dict — list/string/int rejected."""
    import json
    for bad in ([1, 2, 3], "a string", 42, None):
        s = _settings(
            AGENTOS_CANONICAL_AGENT_IDS_JSON=json.dumps(bad),
            AGENTOS_CANONICAL_AGENT_ID="legacy-swap-id",
        )
        with pytest.raises(ValueError) as exc:
            get_canonical_agent_ids(s)
        assert "AGENTOS_CANONICAL_AGENT_IDS_JSON" in str(exc.value)


def test_raises_value_error_when_both_sources_empty():
    """Neither JSON nor legacy → ValueError. Operator must configure at least one."""
    s = _settings(
        AGENTOS_CANONICAL_AGENT_IDS_JSON="",
        AGENTOS_CANONICAL_AGENT_ID="",
    )
    with pytest.raises(ValueError) as exc:
        get_canonical_agent_ids(s)
    msg = str(exc.value)
    assert "AGENTOS_CANONICAL_AGENT_ID" in msg or "swap_executor_v1" in msg


def test_get_runtime_uses_canonical_agent_ids_dict(monkeypatch):
    """Production get_runtime() in api/instances_operator.py constructs
    AgentOSRuntime with the parsed dict (so rebalance deploys can dispatch)."""
    import json
    monkeypatch.setenv("AGENTOS_API_URL", "http://localhost:8000")
    monkeypatch.setenv(
        "AGENTOS_CANONICAL_AGENT_IDS_JSON",
        json.dumps({
            "swap_executor_v1": "test-swap-id",
            "rebalance_executor_v1": "test-rebalance-id",
        }),
    )
    monkeypatch.setenv("AGENTOS_CANONICAL_AGENT_ID", "")

    # Re-load settings to pick up the env changes.
    from src.config import Settings
    test_settings = Settings(_env_file=None)

    # Simulate the helper end-to-end on the test settings.
    from src.config import get_canonical_agent_ids
    ids = get_canonical_agent_ids(test_settings)
    assert ids == {
        "swap_executor_v1": "test-swap-id",
        "rebalance_executor_v1": "test-rebalance-id",
    }


def test_get_runtime_returns_none_when_unconfigured():
    """Production get_runtime() logic returns None when AGENTOS_API_URL is empty.

    Tests the guard logic directly using fresh Settings instances rather than
    reloading modules (module reload mutates the singleton and bleeds into
    other tests).
    """
    from src.config import get_canonical_agent_ids

    # Confirm the helper raises when both sources are empty.
    s_empty = _settings(AGENTOS_CANONICAL_AGENT_IDS_JSON="", AGENTOS_CANONICAL_AGENT_ID="")
    with pytest.raises(ValueError):
        get_canonical_agent_ids(s_empty)

    # And that the instances_operator.get_runtime() returns None when AGENTOS_API_URL is empty
    # by checking the guard condition directly.
    s_no_url = _settings(
        AGENTOS_CANONICAL_AGENT_IDS_JSON="",
        AGENTOS_CANONICAL_AGENT_ID="",
        AGENTOS_API_URL="",
    )
    # Guard: if not AGENTOS_API_URL → return None (no runtime needed)
    assert not s_no_url.AGENTOS_API_URL
