"""Task 14 — RED tests for operator repair endpoints.

Covers the edge-case spec in ``.taskmaster/docs/task14-edge-case-spec.md``
N1-N19:

- Auth gating (missing header / non-admin token / unconfigured admin key)
- GET /failed filtering and projection
- POST /{id}/retry-consent state gate, 404, bad-ack, happy path
- POST /{id}/teardown: no-handle, happy-path, runtime error, corrupt
  handle, already-torn-down idempotency, live-instance teardown,
  unconfigured runtime factory

Pattern mirrors ``tests/test_task11_api.py`` — ``TestClient(app)`` with
``app.dependency_overrides`` for ``get_db`` and the new ``get_runtime``
factory. A small in-memory SQLite engine backs the override so real
rows are created/inspected; the FastAPI route handlers run unchanged.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

os.environ["ADMIN_API_KEY"] = "test-admin-key-secret"
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)

from src.config import settings  # noqa: E402

settings.ADMIN_API_KEY = "test-admin-key-secret"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles  # noqa: E402

from src.db.engine import get_db  # noqa: E402
from src.main import app  # noqa: E402
from src.runtime.base import InstanceHandle  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"


ADMIN_TOKEN = "test-admin-key-secret"
WRONG_TOKEN = "wrong-key"

_VALID_CONFIG = {
    "allowed_token_universe": [
        "So11111111111111111111111111111111111111112",
        "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k",
    ],
    "max_slippage_bps": 100,
    "max_position_size": 1_000_000,
    "max_iterations": 10,
    "max_runtime_seconds": 180,
}

_VALID_CONSENT = {
    "devnet_only_acknowledged": True,
    "platform_managed_signing_acknowledged": True,
    "spend_caps_acknowledged": True,
    "no_indemnity_acknowledged": True,
}


# ---------------------------------------------------------------------
# In-memory DB fixture wired via app.dependency_overrides
# ---------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_engine():
    from sqlalchemy import event

    from src.db.models import Base

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def test_session_factory(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(test_session_factory):
    """TestClient with get_db + get_runtime overrides.

    Save+restore any previous override so we don't clobber sibling test
    modules that set their own module-level overrides (e.g. test_task11_api).
    """
    from src.api import instances_operator as op_module

    async def _override_db():
        async with test_session_factory() as session:
            yield session

    stub_runtime = _StubRuntime()
    sentinel = object()
    prev_db = app.dependency_overrides.get(get_db, sentinel)
    prev_rt = app.dependency_overrides.get(op_module.get_runtime, sentinel)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[op_module.get_runtime] = lambda: stub_runtime
    try:
        with TestClient(app) as c:
            c._stub_runtime = stub_runtime  # expose for assertions
            yield c
    finally:
        if prev_db is sentinel:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = prev_db
        if prev_rt is sentinel:
            app.dependency_overrides.pop(op_module.get_runtime, None)
        else:
            app.dependency_overrides[op_module.get_runtime] = prev_rt


@pytest_asyncio.fixture
async def db(test_session_factory):
    """Separate session for test seeding/assertions."""
    async with test_session_factory() as session:
        yield session


# ---------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------


async def _seed_template(db: AsyncSession) -> int:
    from src.db.models import AgentTemplate

    tmpl = AgentTemplate(
        template_key="swap_executor_v1",
        template_version="swap_executor_v1",
        description="test",
        allowed_fields_json=json.dumps(sorted(_VALID_CONFIG.keys())),
        default_config_json=json.dumps(_VALID_CONFIG),
        system_prompt="x",
        is_deployable=1,
    )
    db.add(tmpl)
    await db.flush()
    await db.commit()
    return tmpl.template_id


async def _seed_instance(
    db: AsyncSession,
    *,
    template_id: int,
    status: str,
    owner_ref: str = "owner-1",
    last_failure_reason: str | None = None,
    runtime_handle_json: str | None = None,
    wallet_address: str = "sol-addr-1",
    hosted_wallet_ref: str = "w-id-1",
) -> int:
    from src.db.models import AgentInstance

    inst = AgentInstance(
        template_id=template_id,
        template_version_at_deploy="swap_executor_v1",
        instance_owner_ref=owner_ref,
        effective_config_json=json.dumps(_VALID_CONFIG, sort_keys=True),
        wallet_address=wallet_address,
        hosted_wallet_ref=hosted_wallet_ref,
        wallet_provider="privy",
        status=status,
        last_failure_reason=last_failure_reason,
        runtime_handle_json=runtime_handle_json,
    )
    db.add(inst)
    await db.flush()
    await db.commit()
    return inst.instance_id


def _live_handle_json() -> str:
    handle = InstanceHandle(
        instance_id="swap-executor-v1",
        extra={"session_id": "sess-abc", "effective_config": dict(_VALID_CONFIG)},
    )
    return json.dumps(asdict(handle))


# ---------------------------------------------------------------------
# Stub runtime (captures teardown calls; optionally raises)
# ---------------------------------------------------------------------


class _StubRuntime:
    def __init__(self):
        self.teardown_calls: list[InstanceHandle] = []
        self.raise_on_teardown: Exception | None = None

    async def deploy(self, spec):  # pragma: no cover — not used here
        raise NotImplementedError

    async def invoke_decide(self, handle, state):  # pragma: no cover
        raise NotImplementedError

    async def teardown(self, handle):
        self.teardown_calls.append(handle)
        if self.raise_on_teardown is not None:
            raise self.raise_on_teardown


# =====================================================================
# Auth gating (N1, N2, N3)
# =====================================================================


def test_list_failed_missing_auth_returns_401(client):
    resp = client.get("/api/v1/instances/operator/failed")
    assert resp.status_code == 401


def test_list_failed_wrong_token_returns_403(client):
    resp = client.get(
        "/api/v1/instances/operator/failed",
        headers={"Authorization": f"Bearer {WRONG_TOKEN}"},
    )
    assert resp.status_code == 403


def test_retry_consent_missing_auth_returns_401(client):
    resp = client.post("/api/v1/instances/operator/1/retry-consent", json={})
    assert resp.status_code == 401


def test_teardown_missing_auth_returns_401(client):
    resp = client.post("/api/v1/instances/operator/1/teardown")
    assert resp.status_code == 401


def test_admin_key_unset_returns_503(client):
    # Temporarily unset ADMIN_API_KEY at settings level (fixture restores).
    original = settings.ADMIN_API_KEY
    settings.ADMIN_API_KEY = ""
    try:
        resp = client.get(
            "/api/v1/instances/operator/failed",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert resp.status_code == 503
    finally:
        settings.ADMIN_API_KEY = original


# =====================================================================
# GET /failed filtering + projection (N4, N5)
# =====================================================================


async def test_list_failed_returns_only_failure_states(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    # Rows in every status we care about.
    id_live = await _seed_instance(db, template_id=tid, status=SagaStatus.LIVE.value)
    id_prov = await _seed_instance(
        db, template_id=tid, status=SagaStatus.PROVISIONING.value
    )
    id_wcr = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.WALLET_CREATED_RUNTIME_FAILED.value,
        last_failure_reason="wallet_created_runtime_failed",
    )
    id_rlc = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
        last_failure_reason="runtime_live_consent_failed",
        runtime_handle_json=_live_handle_json(),
    )
    id_pf = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.PROVISIONING_FAILED.value,
        last_failure_reason="provisioning_failed",
    )
    id_td = await _seed_instance(db, template_id=tid, status=SagaStatus.TORN_DOWN.value)

    resp = client.get(
        "/api/v1/instances/operator/failed",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    ids = {row["instance_id"] for row in body}
    assert ids == {id_wcr, id_rlc, id_pf}
    assert id_live not in ids and id_prov not in ids and id_td not in ids

    # Projection shape (N5)
    sample = next(r for r in body if r["instance_id"] == id_wcr)
    expected_keys = {
        "instance_id",
        "template_id",
        "instance_owner_ref",
        "status",
        "last_failure_reason",
        "hosted_wallet_ref",
        "wallet_address",
        "runtime_handle_json",
        "created_at",
    }
    assert set(sample.keys()) == expected_keys


# =====================================================================
# POST /{id}/retry-consent (N6..N10)
# =====================================================================


async def test_retry_consent_404_for_unknown_instance(client):
    resp = client.post(
        "/api/v1/instances/operator/9999/retry-consent",
        json=_VALID_CONSENT,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 404


async def test_retry_consent_400_when_status_is_live(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(db, template_id=tid, status=SagaStatus.LIVE.value)

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/retry-consent",
        json=_VALID_CONSENT,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 400
    assert "live" in resp.json()["detail"].lower()


async def test_retry_consent_400_when_wrong_failure_class(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.WALLET_CREATED_RUNTIME_FAILED.value,
        last_failure_reason="wallet_created_runtime_failed",
    )

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/retry-consent",
        json=_VALID_CONSENT,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 400


async def test_retry_consent_400_when_acknowledgment_missing(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
        last_failure_reason="runtime_live_consent_failed",
        runtime_handle_json=_live_handle_json(),
    )

    bad_consent = {k: v for k, v in _VALID_CONSENT.items() if k != "no_indemnity_acknowledged"}
    resp = client.post(
        f"/api/v1/instances/operator/{iid}/retry-consent",
        json=bad_consent,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 400
    assert "no_indemnity_acknowledged" in resp.json()["detail"]


async def test_retry_consent_happy_path(client, db):
    from src.db.models import AgentInstance, VerificationArtifact
    from src.integrity.saga_statuses import SagaStatus
    from src.policy.engine import InstancePolicyEngine
    from sqlalchemy import select

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
        last_failure_reason="runtime_live_consent_failed",
        runtime_handle_json=_live_handle_json(),
    )

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/retry-consent",
        json=_VALID_CONSENT,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["instance_id"] == iid
    assert body["status"] == "live"
    assert body["last_failure_reason"] is None
    assert body["consent_artifact_id"] is not None

    # DB state — fresh session to confirm commit.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as s2:
        row = (
            await s2.execute(
                select(AgentInstance).where(AgentInstance.instance_id == iid)
            )
        ).scalar_one()
        assert row.status == "live"
        assert row.last_failure_reason is None
        assert row.consent_artifact_id == body["consent_artifact_id"]

        artifact = (
            await s2.execute(
                select(VerificationArtifact).where(
                    VerificationArtifact.artifact_id == body["consent_artifact_id"]
                )
            )
        ).scalar_one()
        assert artifact.artifact_type == "deployment_consent"
        assert artifact.run_id is None
        expected = InstancePolicyEngine().record_consent(_VALID_CONSENT)
        assert artifact.uri_or_ref == expected.canonical_json
        assert artifact.content_hash == expected.content_hash


# =====================================================================
# POST /{id}/teardown (N11..N19)
# =====================================================================


async def test_teardown_404_for_unknown_instance(client):
    resp = client.post(
        "/api/v1/instances/operator/9999/teardown",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 404


async def test_teardown_without_handle_skips_runtime(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.WALLET_CREATED_RUNTIME_FAILED.value,
        last_failure_reason="wallet_created_runtime_failed",
        runtime_handle_json=None,
    )

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/teardown",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["instance_id"] == iid
    assert body["status"] == "torn_down"
    assert body["runtime_cleanup_ok"] is True

    # Runtime NOT invoked when no handle.
    assert client._stub_runtime.teardown_calls == []


async def test_teardown_happy_path_calls_runtime(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
        last_failure_reason="runtime_live_consent_failed",
        runtime_handle_json=_live_handle_json(),
    )

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/teardown",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "torn_down"
    assert body["runtime_cleanup_ok"] is True

    # Runtime invoked once with the parsed handle.
    assert len(client._stub_runtime.teardown_calls) == 1
    h = client._stub_runtime.teardown_calls[0]
    assert h.instance_id == "swap-executor-v1"
    assert h.extra["session_id"] == "sess-abc"


async def test_teardown_runtime_error_still_transitions_domain_state(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
        last_failure_reason="runtime_live_consent_failed",
        runtime_handle_json=_live_handle_json(),
    )

    client._stub_runtime.raise_on_teardown = RuntimeError("agentos unreachable")

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/teardown",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "torn_down"
    assert body["runtime_cleanup_ok"] is False
    assert "runtime_cleanup_detail" in body


async def test_teardown_corrupt_handle_json_still_succeeds(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
        last_failure_reason="runtime_live_consent_failed",
        runtime_handle_json="{not valid json",
    )

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/teardown",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "torn_down"
    assert body["runtime_cleanup_ok"] is False
    # Runtime never invoked — can't parse handle.
    assert client._stub_runtime.teardown_calls == []


async def test_teardown_on_already_torn_down_is_idempotent(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(db, template_id=tid, status=SagaStatus.TORN_DOWN.value)

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/teardown",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "torn_down"
    assert body["runtime_cleanup_ok"] is True
    assert client._stub_runtime.teardown_calls == []


async def test_teardown_on_live_instance_transitions_to_torn_down(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.LIVE.value,
        runtime_handle_json=_live_handle_json(),
    )

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/teardown",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "torn_down"
    assert body["runtime_cleanup_ok"] is True
    assert len(client._stub_runtime.teardown_calls) == 1


async def test_teardown_with_no_runtime_factory_returns_503_when_handle_present(
    test_session_factory,
):
    """Simulate AgentOS not configured: get_runtime returns None."""
    from src.api import instances_operator as op_module
    from src.integrity.saga_statuses import SagaStatus

    async def _override_db():
        async with test_session_factory() as session:
            yield session

    sentinel = object()
    prev_db = app.dependency_overrides.get(get_db, sentinel)
    prev_rt = app.dependency_overrides.get(op_module.get_runtime, sentinel)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[op_module.get_runtime] = lambda: None
    try:
        # seed an instance with a handle
        async with test_session_factory() as s:
            tid = await _seed_template(s)
            iid = await _seed_instance(
                s,
                template_id=tid,
                status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
                last_failure_reason="runtime_live_consent_failed",
                runtime_handle_json=_live_handle_json(),
            )
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/instances/operator/{iid}/teardown",
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            )
        assert resp.status_code == 503
    finally:
        if prev_db is sentinel:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = prev_db
        if prev_rt is sentinel:
            app.dependency_overrides.pop(op_module.get_runtime, None)
        else:
            app.dependency_overrides[op_module.get_runtime] = prev_rt


# =====================================================================
# Follow-up fix 1 — teardown clears stale last_failure_reason
# =====================================================================


async def test_teardown_from_wallet_created_runtime_failed_clears_reason(client, db):
    from src.integrity.saga_statuses import SagaStatus
    from sqlalchemy import select
    from src.db.models import AgentInstance
    from sqlalchemy.ext.asyncio import async_sessionmaker

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.WALLET_CREATED_RUNTIME_FAILED.value,
        last_failure_reason="wallet_created_runtime_failed",
        runtime_handle_json=None,
    )

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/teardown",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as s2:
        row = (
            await s2.execute(
                select(AgentInstance).where(AgentInstance.instance_id == iid)
            )
        ).scalar_one()
        assert row.status == "torn_down"
        assert row.last_failure_reason is None


async def test_teardown_from_runtime_live_consent_failed_clears_reason(client, db):
    from src.integrity.saga_statuses import SagaStatus
    from sqlalchemy import select
    from src.db.models import AgentInstance
    from sqlalchemy.ext.asyncio import async_sessionmaker

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
        last_failure_reason="runtime_live_consent_failed",
        runtime_handle_json=_live_handle_json(),
    )

    resp = client.post(
        f"/api/v1/instances/operator/{iid}/teardown",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as s2:
        row = (
            await s2.execute(
                select(AgentInstance).where(AgentInstance.instance_id == iid)
            )
        ).scalar_one()
        assert row.status == "torn_down"
        assert row.last_failure_reason is None


async def test_teardown_idempotent_does_not_reintroduce_failure_reason(client, db):
    from src.integrity.saga_statuses import SagaStatus
    from sqlalchemy import select
    from src.db.models import AgentInstance
    from sqlalchemy.ext.asyncio import async_sessionmaker

    tid = await _seed_template(db)
    # Already torn_down with NULL reason (the post-teardown terminal state).
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.TORN_DOWN.value,
        last_failure_reason=None,
    )

    # Two repeat calls — neither should mutate anything.
    for _ in range(2):
        resp = client.post(
            f"/api/v1/instances/operator/{iid}/teardown",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert resp.status_code == 200

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as s2:
        row = (
            await s2.execute(
                select(AgentInstance).where(AgentInstance.instance_id == iid)
            )
        ).scalar_one()
        assert row.status == "torn_down"
        assert row.last_failure_reason is None


# =====================================================================
# Follow-up fix 2 — _RetryConsentBody strict-boolean gating
# =====================================================================


async def test_retry_consent_rejects_string_true_at_schema_layer(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
        last_failure_reason="runtime_live_consent_failed",
        runtime_handle_json=_live_handle_json(),
    )

    coerced_payloads = [
        # Each payload has one non-strict-bool field; the rest are real bools.
        {**_VALID_CONSENT, "devnet_only_acknowledged": "true"},
        {**_VALID_CONSENT, "platform_managed_signing_acknowledged": "1"},
        {**_VALID_CONSENT, "spend_caps_acknowledged": "yes"},
        {**_VALID_CONSENT, "no_indemnity_acknowledged": 1},
    ]
    for payload in coerced_payloads:
        resp = client.post(
            f"/api/v1/instances/operator/{iid}/retry-consent",
            json=payload,
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert resp.status_code == 422, f"payload {payload} unexpectedly accepted: {resp.status_code}"


async def test_retry_consent_400_on_explicit_false_ack(client, db):
    from src.integrity.saga_statuses import SagaStatus

    tid = await _seed_template(db)
    iid = await _seed_instance(
        db,
        template_id=tid,
        status=SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value,
        last_failure_reason="runtime_live_consent_failed",
        runtime_handle_json=_live_handle_json(),
    )

    bad_payload = {**_VALID_CONSENT, "spend_caps_acknowledged": False}
    resp = client.post(
        f"/api/v1/instances/operator/{iid}/retry-consent",
        json=bad_payload,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    # Schema accepts; policy engine rejects → 400 with named field in detail.
    assert resp.status_code == 400
    assert "spend_caps_acknowledged" in resp.json()["detail"]


async def test_teardown_with_no_runtime_factory_ok_when_no_handle(
    test_session_factory,
):
    """AgentOS unconfigured but instance has no handle → 200, no runtime needed."""
    from src.api import instances_operator as op_module
    from src.integrity.saga_statuses import SagaStatus

    async def _override_db():
        async with test_session_factory() as session:
            yield session

    sentinel = object()
    prev_db = app.dependency_overrides.get(get_db, sentinel)
    prev_rt = app.dependency_overrides.get(op_module.get_runtime, sentinel)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[op_module.get_runtime] = lambda: None
    try:
        async with test_session_factory() as s:
            tid = await _seed_template(s)
            iid = await _seed_instance(
                s,
                template_id=tid,
                status=SagaStatus.WALLET_CREATED_RUNTIME_FAILED.value,
                last_failure_reason="wallet_created_runtime_failed",
                runtime_handle_json=None,
            )
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/instances/operator/{iid}/teardown",
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "torn_down"
        assert body["runtime_cleanup_ok"] is True
    finally:
        if prev_db is sentinel:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = prev_db
        if prev_rt is sentinel:
            app.dependency_overrides.pop(op_module.get_runtime, None)
        else:
            app.dependency_overrides[op_module.get_runtime] = prev_rt
