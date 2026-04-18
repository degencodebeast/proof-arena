"""Task 11: API Endpoints — TDD tests with real auth enforcement."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# Set admin key and patch settings
os.environ["ADMIN_API_KEY"] = "test-admin-key-secret"

from src.config import settings
settings.ADMIN_API_KEY = "test-admin-key-secret"

from src.db.engine import get_db
from src.main import app


def _mock_db():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one.return_value = 0  # For count queries
    mock_result.__iter__ = MagicMock(return_value=iter([]))
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


mock_db_instance = _mock_db()

async def override_get_db():
    yield mock_db_instance

app.dependency_overrides[get_db] = override_get_db
# Auth is NOT overridden — real auth.py logic runs

client = TestClient(app)

USER_TOKEN = "user-api-key-123"
ADMIN_TOKEN = "test-admin-key-secret"
WRONG_TOKEN = "wrong-key"


# -----------------------------------------------------------------------
# Leaderboard
# -----------------------------------------------------------------------


class TestLeaderboard:
    def test_returns_200(self):
        assert client.get("/api/v1/leaderboard").status_code == 200

    def test_returns_list(self):
        assert isinstance(client.get("/api/v1/leaderboard").json(), list)

    def test_respects_limit(self):
        assert client.get("/api/v1/leaderboard?limit=5").status_code == 200

    def test_respects_offset(self):
        assert client.get("/api/v1/leaderboard?limit=5&offset=10").status_code == 200

    def test_rejects_excessive_limit(self):
        assert client.get("/api/v1/leaderboard?limit=999").status_code == 422


# -----------------------------------------------------------------------
# Agent profile
# -----------------------------------------------------------------------


class TestAgentProfile:
    def test_missing_returns_404(self):
        assert client.get("/api/v1/agents/99999").status_code == 404

    def test_404_has_detail(self):
        resp = client.get("/api/v1/agents/99999")
        assert "not found" in resp.json()["detail"].lower()


# -----------------------------------------------------------------------
# Challenges
# -----------------------------------------------------------------------


class TestChallenges:
    def test_list_returns_200(self):
        assert client.get("/api/v1/challenges").status_code == 200

    def test_list_supports_filter(self):
        assert client.get("/api/v1/challenges?status=active").status_code == 200

    def test_detail_missing_returns_404(self):
        assert client.get("/api/v1/challenges/99999").status_code == 404

    def test_events_missing_returns_404(self):
        assert client.get("/api/v1/challenges/99999/events").status_code == 404


# -----------------------------------------------------------------------
# Strategy submission — auth enforcement
# -----------------------------------------------------------------------


class TestStrategyAuth:
    def test_no_token_returns_401(self):
        resp = client.post("/api/v1/strategies", json={
            "agent_name": "Test", "system_prompt": "Do swaps.",
        })
        assert resp.status_code == 401

    def test_with_token_reaches_handler(self):
        resp = client.post("/api/v1/strategies",
            json={"agent_name": "Test", "system_prompt": "Do swaps."},
            headers={"Authorization": f"Bearer {USER_TOKEN}"},
        )
        # Should reach handler (may fail on mock DB), not 401
        assert resp.status_code in (200, 422, 500)

    def test_missing_fields_returns_422(self):
        resp = client.post("/api/v1/strategies", json={},
            headers={"Authorization": f"Bearer {USER_TOKEN}"},
        )
        assert resp.status_code == 422

    def test_user_identity_from_token(self):
        """The privy_user_id should be the token value, not a hardcoded stub."""
        mock_agent = MagicMock()
        mock_agent.agent_id = 1
        mock_agent.display_name = "Bot"
        mock_agent.submission_hash = "abc"
        mock_agent.onchain_address = None

        captured_user_id = None

        class MockService:
            def __init__(self, db):
                pass
            async def get_active_count(self, uid):
                nonlocal captured_user_id
                captured_user_id = uid
                return 0
            async def register_strategy(self, **kwargs):
                return mock_agent

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.api.strategies.StrategyService", MockService)
            client.post("/api/v1/strategies",
                json={"agent_name": "Bot", "system_prompt": "test"},
                headers={"Authorization": f"Bearer {USER_TOKEN}"},
            )
        assert captured_user_id == USER_TOKEN  # Not "stub-user"

    def test_anti_spam_rejects(self):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.api.strategies.StrategyService",
                lambda db: MagicMock(get_active_count=AsyncMock(return_value=99)),
            )
            resp = client.post("/api/v1/strategies",
                json={"agent_name": "Spam", "system_prompt": "spam"},
                headers={"Authorization": f"Bearer {USER_TOKEN}"},
            )
            assert resp.status_code == 429


# -----------------------------------------------------------------------
# Admin — real auth enforcement
# -----------------------------------------------------------------------


class TestAdminAuth:
    def test_no_token_returns_401(self):
        resp = client.post("/api/v1/admin/challenges", json={
            "starting_usdc": 100_000_000, "swap_intents": ["SOL"],
            "contestant_agent_ids": [1],
        })
        assert resp.status_code == 401

    def test_wrong_token_returns_403(self):
        resp = client.post("/api/v1/admin/challenges",
            json={"starting_usdc": 100_000_000, "swap_intents": ["SOL"],
                  "contestant_agent_ids": [1]},
            headers={"Authorization": f"Bearer {WRONG_TOKEN}"},
        )
        assert resp.status_code == 403

    def test_user_token_returns_403(self):
        """A valid user token that is not the admin key must get 403."""
        resp = client.post("/api/v1/admin/challenges",
            json={"starting_usdc": 100_000_000, "swap_intents": ["SOL"],
                  "contestant_agent_ids": [1]},
            headers={"Authorization": f"Bearer {USER_TOKEN}"},
        )
        assert resp.status_code == 403

    def test_admin_token_reaches_handler(self):
        resp = client.post("/api/v1/admin/challenges",
            json={"starting_usdc": 100_000_000, "swap_intents": ["SOL"],
                  "contestant_agent_ids": [1]},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        # Should reach handler (may fail on service), not 401/403
        assert resp.status_code not in (401, 403)

    def test_start_no_token_returns_401(self):
        assert client.post("/api/v1/admin/challenges/1/start").status_code == 401

    def test_start_wrong_token_returns_403(self):
        resp = client.post("/api/v1/admin/challenges/1/start",
            headers={"Authorization": f"Bearer {WRONG_TOKEN}"},
        )
        assert resp.status_code == 403

    def test_start_admin_token_reaches_handler(self):
        resp = client.post("/api/v1/admin/challenges/1/start",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert resp.status_code not in (401, 403)


# -----------------------------------------------------------------------
# Read-model correctness with mock data
# -----------------------------------------------------------------------


class TestReadModelCorrectness:
    def test_leaderboard_returns_mock_entries(self):
        """Leaderboard with seeded mock data returns entries."""
        from unittest.mock import MagicMock
        from datetime import datetime, timezone

        mock_snapshot = MagicMock()
        mock_snapshot.agent_id = 1
        mock_snapshot.score = 85.5
        mock_snapshot.rank_version = "rank_v1"
        mock_snapshot.wins = 3
        mock_snapshot.losses = 1
        mock_snapshot.completed_runs = 4
        mock_snapshot.invalid_runs = 0

        mock_agent = MagicMock()
        mock_agent.agent_id = 1
        mock_agent.display_name = "TestBot"
        mock_agent.status = "active"
        mock_agent.twitter_handle = None

        # Override db to return mock data
        mock_db = _mock_db()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([(mock_snapshot, mock_agent)]))
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def seeded_db():
            yield mock_db

        app.dependency_overrides[get_db] = seeded_db
        try:
            resp = client.get("/api/v1/leaderboard")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["display_name"] == "TestBot"
            assert data[0]["score"] == 85.5
        finally:
            app.dependency_overrides[get_db] = override_get_db

    def test_agent_profile_returns_shape(self):
        """Agent profile with seeded agent returns expected fields."""
        mock_agent = MagicMock()
        mock_agent.agent_id = 1
        mock_agent.display_name = "TestBot"
        mock_agent.owner_wallet = "wallet123"
        mock_agent.submission_hash = "abc"
        mock_agent.twitter_handle = None

        mock_db = _mock_db()
        mock_db.get = AsyncMock(return_value=mock_agent)

        # Return no rank/runs
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_result.scalars.return_value = MagicMock(__iter__=lambda s: iter([]))
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def seeded_db():
            yield mock_db

        app.dependency_overrides[get_db] = seeded_db
        try:
            resp = client.get("/api/v1/agents/1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["agent_id"] == 1
            assert data["display_name"] == "TestBot"
            assert data["submission_hash"] == "abc"
            assert "current_rank" in data
            assert "recent_runs" in data
            assert "score_breakdown" in data
            # Must NOT expose system_prompt
            assert "system_prompt" not in data
        finally:
            app.dependency_overrides[get_db] = override_get_db


# -----------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------


class TestImports:
    def test_router_exists(self):
        from src.api.router import api_router
        assert api_router is not None

    def test_api_mounted(self):
        routes = [r.path for r in app.routes]
        assert any("/api/v1" in r for r in routes)
