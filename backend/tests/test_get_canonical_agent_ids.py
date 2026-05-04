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


def test_get_runtime_constructs_runtime_with_multi_template_dict(monkeypatch):
    """Production wiring lock: api/instances_operator.get_runtime() actually
    builds AgentOSRuntime with the multi-template dict from the JSON env var.

    This test is REGRESSION-LOCK over the test-coverage gap Codex caught:
    the prior `test_get_runtime_uses_canonical_agent_ids_dict` claimed to
    exercise production wiring but only called the helper directly. This
    test patches `src.api.instances_operator.settings` with a Settings
    instance that has AGENTOS_CANONICAL_AGENT_IDS_JSON populated, calls
    `get_runtime()` for real, and asserts the returned AgentOSRuntime's
    `_canonical_agent_ids` has both swap and rebalance keys.

    If a future implementer reverts the production call site to pass
    `canonical_agent_id=settings.AGENTOS_CANONICAL_AGENT_ID`, this test
    fails with `KeyError: 'rebalance_executor_v1'` or equivalent.
    """
    import json

    from src.api import instances_operator
    from src.config import Settings

    test_settings = Settings(
        _env_file=None,
        AGENTOS_API_URL="http://localhost:8000",
        AGENTOS_AUTH_TOKEN="",
        AGENTOS_CANONICAL_AGENT_IDS_JSON=json.dumps({
            "swap_executor_v1": "test-swap-id",
            "rebalance_executor_v1": "test-rebalance-id",
        }),
        AGENTOS_CANONICAL_AGENT_ID="",
    )
    # Patch the module-level `settings` reference inside instances_operator;
    # do NOT use importlib.reload (which mutates the global singleton and
    # bleeds across tests, per Task 7 follow-up implementer's notes).
    monkeypatch.setattr(instances_operator, "settings", test_settings)

    runtime = instances_operator.get_runtime()
    assert runtime is not None, (
        "get_runtime() returned None despite AGENTOS_API_URL + JSON env var being set"
    )
    assert runtime._canonical_agent_ids == {
        "swap_executor_v1": "test-swap-id",
        "rebalance_executor_v1": "test-rebalance-id",
    }, (
        f"Production wiring regression: get_runtime() did not pass the parsed "
        f"dict to AgentOSRuntime; got _canonical_agent_ids={runtime._canonical_agent_ids!r}"
    )


def test_get_runtime_returns_none_when_api_url_unset(monkeypatch):
    """Production guard: AGENTOS_API_URL empty → get_runtime() returns None
    (cannot construct runtime without an endpoint)."""
    from src.api import instances_operator
    from src.config import Settings

    test_settings = Settings(
        _env_file=None,
        AGENTOS_API_URL="",   # missing endpoint
        AGENTOS_AUTH_TOKEN="",
        AGENTOS_CANONICAL_AGENT_IDS_JSON="",
        AGENTOS_CANONICAL_AGENT_ID="swap_executor_v1",  # legacy still set; doesn't matter without API URL
    )
    monkeypatch.setattr(instances_operator, "settings", test_settings)
    assert instances_operator.get_runtime() is None


def test_get_runtime_returns_none_when_no_canonical_agent_id_source(monkeypatch):
    """Production guard: AGENTOS_API_URL set but neither JSON map nor legacy
    string set → get_runtime() returns None (helper raises ValueError;
    production wraps it as None per the unconfigured pattern)."""
    from src.api import instances_operator
    from src.config import Settings

    test_settings = Settings(
        _env_file=None,
        AGENTOS_API_URL="http://localhost:8000",
        AGENTOS_AUTH_TOKEN="",
        AGENTOS_CANONICAL_AGENT_IDS_JSON="",
        AGENTOS_CANONICAL_AGENT_ID="",
    )
    monkeypatch.setattr(instances_operator, "settings", test_settings)
    assert instances_operator.get_runtime() is None


def test_get_runtime_legacy_back_compat_via_singular_env_var(monkeypatch):
    """Production back-compat lock: legacy AGENTOS_CANONICAL_AGENT_ID alone
    (no JSON map) still produces a runtime with `{swap_executor_v1: <id>}`."""
    from src.api import instances_operator
    from src.config import Settings

    test_settings = Settings(
        _env_file=None,
        AGENTOS_API_URL="http://localhost:8000",
        AGENTOS_AUTH_TOKEN="",
        AGENTOS_CANONICAL_AGENT_IDS_JSON="",   # JSON unset
        AGENTOS_CANONICAL_AGENT_ID="legacy-swap-only-id",
    )
    monkeypatch.setattr(instances_operator, "settings", test_settings)

    runtime = instances_operator.get_runtime()
    assert runtime is not None
    assert runtime._canonical_agent_ids == {"swap_executor_v1": "legacy-swap-only-id"}, (
        f"Legacy back-compat regression: got _canonical_agent_ids={runtime._canonical_agent_ids!r}"
    )
