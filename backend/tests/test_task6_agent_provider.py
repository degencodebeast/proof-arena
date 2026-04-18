"""Task 6: LocalAgentProvider and Arena Agent tests — hardened.

All LLM calls mocked. Tests verify strict parsing, real state validation,
OpenRouter support, and no loose NL fallback.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.challenges.base import ChallengeState
from src.db.schemas import AgentAction, AgentActionType


def _make_state(**overrides) -> ChallengeState:
    defaults = {
        "portfolio": {"USDC": 1_000_000_000},
        "completed_swaps": [],
        "required_swaps": ["SOL"],
        "iterations_used": 0,
        "elapsed_secs": 0.0,
        "iteration_budget": 20,
        "time_budget_secs": 300,
        "status": "active",
    }
    defaults.update(overrides)
    return ChallengeState(**defaults)


# -----------------------------------------------------------------------
# 1. Arena Agent creation + OpenRouter
# -----------------------------------------------------------------------


class TestArenaAgentCreation:
    def test_create_model_anthropic(self):
        from src.agents.arena_agent import _create_model
        from agno.models.anthropic import Claude

        model = _create_model("anthropic", "claude-sonnet-4-20250514")
        assert isinstance(model, Claude)

    def test_create_model_openrouter(self):
        from src.agents.arena_agent import _create_model
        from agno.models.openrouter import OpenRouter

        model = _create_model("openrouter", "anthropic/claude-sonnet-4")
        assert isinstance(model, OpenRouter)

    def test_openrouter_no_fallback_models(self):
        """OpenRouter must use explicit model ID, no auto-routing."""
        from src.agents.arena_agent import _create_model

        model = _create_model("openrouter", "openai/gpt-4o")
        # Verify no fallback models list is set
        assert not getattr(model, "models", None)

    def test_unsupported_provider_raises(self):
        from src.agents.arena_agent import _create_model

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            _create_model("unknown", "model")

    def test_supported_providers_listed_in_error(self):
        from src.agents.arena_agent import _create_model

        with pytest.raises(ValueError, match="openrouter"):
            _create_model("bad", "model")

    def test_agent_receives_tools(self):
        from src.agents.arena_agent import create_arena_agent

        agent = create_arena_agent(
            system_prompt="Test",
            llm_provider="anthropic",
            llm_model="claude-sonnet-4-20250514",
            tools=[MagicMock()],
        )
        assert len(agent.tools) >= 1

    def test_agent_has_no_memory_or_knowledge(self):
        from src.agents.arena_agent import create_arena_agent

        agent = create_arena_agent(
            system_prompt="Test",
            llm_provider="anthropic",
            llm_model="claude-sonnet-4-20250514",
            tools=[],
        )
        assert not getattr(agent, "memory", None)
        assert not getattr(agent, "knowledge", None)
        assert not getattr(agent, "storage", None)


# -----------------------------------------------------------------------
# 2. observe_state tool
# -----------------------------------------------------------------------


class TestObserveStateTool:
    @pytest.mark.asyncio
    async def test_returns_structured_json(self):
        from src.tools.observe_state import create_observe_state_tool

        mock_ws = MagicMock()
        mock_ws.get_token_balances = AsyncMock(return_value={"USDC": 1_000_000})
        tool_fn = create_observe_state_tool(mock_ws, "walletAddr")
        data = json.loads(await tool_fn.entrypoint())
        assert data["balances"]["USDC"] == 1_000_000
        assert "timestamp" in data


# -----------------------------------------------------------------------
# 3. get_quotes tool
# -----------------------------------------------------------------------


class TestGetQuotesTool:
    @pytest.mark.asyncio
    async def test_rejects_disallowed_pair(self):
        from src.tools.get_quotes import create_get_quotes_tool

        mock_js = MagicMock()
        tool_fn = create_get_quotes_tool(mock_js, [("SOL", "USDC")])
        data = json.loads(await tool_fn.entrypoint("BTC", "ETH", 1000))
        assert "not allowed" in data["error"]
        mock_js.get_quotes.assert_not_called()

    @pytest.mark.asyncio
    async def test_allows_valid_pair(self):
        from src.services.jupiter_service import QuoteOption
        from src.tools.get_quotes import create_get_quotes_tool

        mock_js = MagicMock()
        mock_js.get_quotes = AsyncMock(return_value=[
            QuoteOption(
                quote_id="q1", input_mint="SOL", output_mint="USDC",
                in_amount=100, out_amount=90, slippage_bps=100,
                fetched_at="2025-01-01T00:00:00Z", route_data={},
            )
        ])
        tool_fn = create_get_quotes_tool(mock_js, [("SOL", "USDC")])
        data = json.loads(await tool_fn.entrypoint("SOL", "USDC", 100))
        assert data[0]["quote_id"] == "q1"


# -----------------------------------------------------------------------
# 4. execute_swap tool — real state validation
# -----------------------------------------------------------------------


class TestExecuteSwapTool:
    @pytest.mark.asyncio
    async def test_successful_swap(self):
        from src.tools.execute_swap import create_execute_swap_tool

        mock_js = MagicMock()
        mock_js.prepare_swap_transaction = AsyncMock(return_value=b"\x01")
        mock_ws = MagicMock()
        mock_ws.sign_and_send_transaction = AsyncMock(return_value="tx_ok")

        tool_fn = create_execute_swap_tool(mock_js, mock_ws, "w", "a")
        data = json.loads(await tool_fn.entrypoint("q1", 100))
        assert data["executed"] is True

    @pytest.mark.asyncio
    async def test_stale_quote(self):
        from src.services.jupiter_service import StaleQuoteError
        from src.tools.execute_swap import create_execute_swap_tool

        mock_js = MagicMock()
        mock_js.prepare_swap_transaction = AsyncMock(
            side_effect=StaleQuoteError("q1", 35.0, 30),
        )

        tool_fn = create_execute_swap_tool(mock_js, MagicMock(), "w", "a")
        data = json.loads(await tool_fn.entrypoint("q1", 100))
        assert data["executed"] is False
        assert "Stale" in data["error"]

    @pytest.mark.asyncio
    async def test_invalid_slippage_rejected(self):
        from src.tools.execute_swap import create_execute_swap_tool

        tool_fn = create_execute_swap_tool(MagicMock(), MagicMock(), "w", "a")
        data = json.loads(await tool_fn.entrypoint("q1", 501))
        assert data["executed"] is False

    @pytest.mark.asyncio
    async def test_validator_receives_real_state(self):
        """Validator must receive the real current state, not {}."""
        from src.tools.execute_swap import create_execute_swap_tool
        from src.integrity import ValidationResult

        captured_state = {}

        async def capture_validate(action, state):
            nonlocal captured_state
            captured_state = state
            return ValidationResult(valid=True)

        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock(side_effect=capture_validate)

        real_state = {"iterations_used": 5, "budget": 20}
        mock_js = MagicMock()
        mock_js.prepare_swap_transaction = AsyncMock(return_value=b"\x01")
        mock_ws = MagicMock()
        mock_ws.sign_and_send_transaction = AsyncMock(return_value="tx")

        tool_fn = create_execute_swap_tool(
            mock_js, mock_ws, "w", "a",
            action_validator=mock_validator,
            get_current_state=lambda: real_state,
        )
        await tool_fn.entrypoint("q1", 100)

        assert captured_state == real_state
        assert captured_state.get("iterations_used") == 5

    @pytest.mark.asyncio
    async def test_state_dependent_validation_failure(self):
        """Validator rejects based on state (e.g., budget exceeded)."""
        from src.tools.execute_swap import create_execute_swap_tool
        from src.integrity import ValidationResult

        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock(
            return_value=ValidationResult(valid=False, reason="Budget exceeded"),
        )

        tool_fn = create_execute_swap_tool(
            MagicMock(), MagicMock(), "w", "a",
            action_validator=mock_validator,
            get_current_state=lambda: {"iterations_used": 20, "budget": 20},
        )
        data = json.loads(await tool_fn.entrypoint("q1", 100))
        assert data["executed"] is False

    @pytest.mark.asyncio
    async def test_validator_without_state_accessor_fails_closed(self):
        """Validator present but no state accessor → fail closed, not {}."""
        from src.tools.execute_swap import create_execute_swap_tool

        mock_validator = MagicMock()
        # Validator should never be called
        mock_validator.validate = AsyncMock()

        tool_fn = create_execute_swap_tool(
            MagicMock(), MagicMock(), "w", "a",
            action_validator=mock_validator,
            get_current_state=None,  # No state accessor
        )
        data = json.loads(await tool_fn.entrypoint("q1", 100))
        assert data["executed"] is False
        assert "no state accessor" in data["error"].lower()
        mock_validator.validate.assert_not_called()


# -----------------------------------------------------------------------
# 5. _format_state_prompt
# -----------------------------------------------------------------------


class TestFormatStatePrompt:
    def test_includes_key_fields(self):
        from src.providers.local_provider import LocalAgentProvider

        prompt = LocalAgentProvider._format_state_prompt(
            _make_state(portfolio={"USDC": 500}, required_swaps=["SOL", "RAY"])
        )
        assert "USDC" in prompt
        assert "SOL" in prompt
        assert "EXECUTE_SWAP" in prompt

    def test_stable(self):
        from src.providers.local_provider import LocalAgentProvider

        s = _make_state()
        assert LocalAgentProvider._format_state_prompt(s) == LocalAgentProvider._format_state_prompt(s)


# -----------------------------------------------------------------------
# 6. _parse_action — STRICT parsing
# -----------------------------------------------------------------------


class TestParseAction:
    def test_clean_json_finish(self):
        from src.providers.local_provider import LocalAgentProvider

        action = LocalAgentProvider._parse_action('{"type": "FINISH", "params": {}}')
        assert action.type == AgentActionType.FINISH

    def test_clean_json_execute_swap(self):
        from src.providers.local_provider import LocalAgentProvider

        raw = '{"type": "EXECUTE_SWAP", "params": {"quote_id": "q1", "max_slippage_bps": 100}}'
        action = LocalAgentProvider._parse_action(raw)
        assert action.type == AgentActionType.EXECUTE_SWAP
        assert action.params["quote_id"] == "q1"

    def test_json_in_code_block(self):
        from src.providers.local_provider import LocalAgentProvider

        raw = '```json\n{"type": "FINISH", "params": {}}\n```'
        action = LocalAgentProvider._parse_action(raw)
        assert action.type == AgentActionType.FINISH

    def test_nested_execute_swap_in_code_block(self):
        """Nested params object in markdown code block must parse correctly."""
        from src.providers.local_provider import LocalAgentProvider

        raw = '```json\n{"type": "EXECUTE_SWAP", "params": {"quote_id": "abc-123", "max_slippage_bps": 50}}\n```'
        action = LocalAgentProvider._parse_action(raw)
        assert action.type == AgentActionType.EXECUTE_SWAP
        assert action.params["quote_id"] == "abc-123"
        assert action.params["max_slippage_bps"] == 50

    def test_nested_json_embedded_in_text(self):
        """Nested JSON object in prose text must parse correctly."""
        from src.providers.local_provider import LocalAgentProvider

        raw = 'I will execute: {"type": "EXECUTE_SWAP", "params": {"quote_id": "xyz", "max_slippage_bps": 75}} now.'
        action = LocalAgentProvider._parse_action(raw)
        assert action.type == AgentActionType.EXECUTE_SWAP
        assert action.params["quote_id"] == "xyz"

    def test_no_natural_language_finish_from_prose(self):
        """Words like 'done' or 'complete' in prose must NOT trigger FINISH.

        This is the key safety fix: the old parser would turn
        'I have completed the analysis' into a FINISH action.
        """
        from src.providers.local_provider import LocalAgentProvider, ActionParseError

        with pytest.raises(ActionParseError):
            LocalAgentProvider._parse_action(
                "I have completed the analysis and I'm done reviewing the options."
            )

    def test_no_natural_language_wait_from_prose(self):
        """The word 'wait' in prose must NOT trigger WAIT."""
        from src.providers.local_provider import LocalAgentProvider, ActionParseError

        with pytest.raises(ActionParseError):
            LocalAgentProvider._parse_action(
                "Please wait while I think about the best strategy."
            )

    def test_empty_response_raises(self):
        from src.providers.local_provider import LocalAgentProvider, ActionParseError

        with pytest.raises(ActionParseError, match="Empty response"):
            LocalAgentProvider._parse_action("")

    def test_pure_gibberish_raises(self):
        from src.providers.local_provider import LocalAgentProvider, ActionParseError

        with pytest.raises(ActionParseError):
            LocalAgentProvider._parse_action("random gibberish 12345")

    def test_json_with_wrong_type_raises(self):
        """Valid JSON but not a valid action type must raise."""
        from src.providers.local_provider import LocalAgentProvider, ActionParseError

        with pytest.raises(ActionParseError):
            LocalAgentProvider._parse_action('{"type": "INVALID", "params": {}}')

    def test_json_without_type_field_raises(self):
        from src.providers.local_provider import LocalAgentProvider, ActionParseError

        with pytest.raises(ActionParseError):
            LocalAgentProvider._parse_action('{"action": "FINISH"}')


# -----------------------------------------------------------------------
# 7. LocalAgentProvider.decide()
# -----------------------------------------------------------------------


class TestLocalAgentProviderDecide:
    @pytest.mark.asyncio
    async def test_decide_returns_agent_action(self):
        from src.providers.local_provider import LocalAgentProvider

        provider = LocalAgentProvider.__new__(LocalAgentProvider)
        provider.system_prompt = "test"
        provider.config = {}

        mock_response = MagicMock()
        mock_response.content = '{"type": "FINISH", "params": {}}'
        mock_response.messages = []
        provider.agent = MagicMock()
        provider.agent.arun = AsyncMock(return_value=mock_response)

        action = await provider.decide(_make_state())
        assert action.type == AgentActionType.FINISH

    @pytest.mark.asyncio
    async def test_decide_with_execute_swap(self):
        from src.providers.local_provider import LocalAgentProvider

        provider = LocalAgentProvider.__new__(LocalAgentProvider)
        provider.system_prompt = "test"
        provider.config = {}

        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "type": "EXECUTE_SWAP",
            "params": {"quote_id": "abc", "max_slippage_bps": 50},
        })
        mock_response.messages = []
        provider.agent = MagicMock()
        provider.agent.arun = AsyncMock(return_value=mock_response)

        action = await provider.decide(_make_state())
        assert action.type == AgentActionType.EXECUTE_SWAP
        assert action.params["quote_id"] == "abc"


# -----------------------------------------------------------------------
# 8. Integration test
# -----------------------------------------------------------------------


class TestIntegration:
    @pytest.mark.asyncio
    async def test_provider_produces_valid_action(self):
        from src.providers.local_provider import LocalAgentProvider

        provider = LocalAgentProvider.__new__(LocalAgentProvider)
        provider.system_prompt = "Execute swaps."
        provider.config = {}

        mock_response = MagicMock()
        mock_response.content = '{"type": "EXECUTE_SWAP", "params": {"quote_id": "test-q", "max_slippage_bps": 100}}'
        mock_response.messages = []
        provider.agent = MagicMock()
        provider.agent.arun = AsyncMock(return_value=mock_response)

        action = await provider.decide(_make_state())
        assert isinstance(action, AgentAction)
        assert action.type == AgentActionType.EXECUTE_SWAP


# -----------------------------------------------------------------------
# 9. Module imports
# -----------------------------------------------------------------------


class TestImports:
    def test_all(self):
        from src.agents.arena_agent import create_arena_agent, SUPPORTED_PROVIDERS
        from src.providers.local_provider import LocalAgentProvider, ActionParseError
        from src.tools.observe_state import create_observe_state_tool
        from src.tools.get_quotes import create_get_quotes_tool
        from src.tools.execute_swap import create_execute_swap_tool

        assert "openrouter" in SUPPORTED_PROVIDERS
        assert all([
            create_arena_agent, LocalAgentProvider, ActionParseError,
            create_observe_state_tool, create_get_quotes_tool,
            create_execute_swap_tool,
        ])
