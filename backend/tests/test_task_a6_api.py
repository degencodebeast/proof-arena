"""Task 1 / A-6 — RED tests for GET /api/v1/failure-taxonomy.

Covers:
- 200 + expected JSON shape
- response keys byte-equal to enum values
- public access (no auth required)

See .taskmaster/docs/task1-edge-case-spec.md.
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient


# NOTE: do NOT rewrite ``settings.ADMIN_API_KEY`` here. This endpoint is
# public (no auth), and mutating the admin key at module import time
# pollutes other test modules (e.g. test_task11_api.py) that rely on their
# own admin-key value.
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-a6-api")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)

from src.main import app


client = TestClient(app)


# Test 11 --------------------------------------------------------------


def test_api_returns_taxonomy_shape():
    """GET /api/v1/failure-taxonomy returns 200 with saga + run sub-maps."""
    resp = client.get("/api/v1/failure-taxonomy")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "saga_failure_reasons" in body
    assert "run_invalid_reasons" in body
    assert isinstance(body["saga_failure_reasons"], dict)
    assert isinstance(body["run_invalid_reasons"], dict)

    # Every entry has title + description
    for bucket in ("saga_failure_reasons", "run_invalid_reasons"):
        for key, copy in body[bucket].items():
            assert isinstance(copy, dict), f"{bucket}.{key} not a dict"
            assert copy.get("title"), f"{bucket}.{key} missing title"
            assert copy.get("description"), f"{bucket}.{key} missing description"


# Test 12 --------------------------------------------------------------


def test_api_keys_match_enum_values():
    """Response keys byte-equal SagaFailureReason + RunInvalidReason .value."""
    from src.integrity.failure_taxonomy import RunInvalidReason, SagaFailureReason

    body = client.get("/api/v1/failure-taxonomy").json()

    saga_expected = {m.value for m in SagaFailureReason}
    run_expected = {m.value for m in RunInvalidReason}

    assert set(body["saga_failure_reasons"].keys()) == saga_expected
    assert set(body["run_invalid_reasons"].keys()) == run_expected


# Test 13 --------------------------------------------------------------


def test_api_public_no_auth():
    """The endpoint is publicly accessible (no Authorization header required)."""
    # No headers at all — must not 401/403.
    resp = client.get("/api/v1/failure-taxonomy")
    assert resp.status_code == 200, resp.text
    # Also verify a clearly-wrong auth header does not change the 200.
    resp2 = client.get(
        "/api/v1/failure-taxonomy",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert resp2.status_code == 200, resp2.text
