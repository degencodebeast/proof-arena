"""Public Verifier V0 — 19 acceptance tests for GET /api/v1/verifier/runs/{run_id}.

Helpers (_seed_template, _seed_instance, _seed_bridge_agent, _seed_run, http_client)
are duplicated from tests/integration/test_wallet_safety_cat.py intentionally,
to keep the Verifier and Cat test files independently audit-able. If the helpers
diverge later, that is a deliberate signal to revisit factoring into a shared
module — not now.
"""
from __future__ import annotations

import json
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.db.models import Agent, AgentInstance, AgentTemplate, Run
from src.main import app
from src.integrity.cats.wallet_safety import compute_wallet_safety_cat


_ENV = json.dumps({
    "allowed_token_universe": ["SOL", "devUSDC"],
    "max_slippage_bps": 50,
    "max_position_size": 1_000_000,
    "max_iterations": 8,
    "max_runtime_seconds": 180,
})


async def _seed_template(db: AsyncSession) -> int:
    template = AgentTemplate(
        template_key="swap_executor_v1",
        template_version="1",
        description="Canonical swap executor template",
        allowed_fields_json=_ENV,
        default_config_json=_ENV,
        system_prompt="balanced",  # AgentTemplate.system_prompt is non-nullable.
        is_deployable=True,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template.template_id


async def _seed_instance(
    db: AsyncSession,
    *,
    template_id: int,
    trust_label: str = "benchmark_compatible_customized_instance",
    instance_owner_ref: str = "owner-1",
    status: str = "live",
) -> AgentInstance:
    instance = AgentInstance(
        template_id=template_id,
        template_version_at_deploy="1",
        instance_owner_ref=instance_owner_ref,
        effective_config_json=_ENV,
        runtime_handle_json=json.dumps({"handle": "fake"}),
        wallet_address="SoLAddrxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        hosted_wallet_ref="hw-1",
        wallet_provider="privy",
        trust_label=trust_label,
        status=status,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return instance


async def _seed_bridge_agent(
    db: AsyncSession,
    *,
    instance_id: int,
    subject_type: str = "customized_instance",
    use_metadata_ref: bool = True,
    privy_user_id_override: str | None = None,
    metadata_ref_override: str | None = None,
) -> Agent:
    agent = Agent(
        subject_type=subject_type,
        privy_user_id=(
            privy_user_id_override
            if privy_user_id_override is not None
            else f"instance:{instance_id}"
        ),
        metadata_ref=(
            metadata_ref_override
            if metadata_ref_override is not None
            else (f"agent_instances/{instance_id}" if use_metadata_ref else None)
        ),
        owner_wallet="SoLAgentxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        submission_hash="a" * 64,
        system_prompt="x",          # Agent.system_prompt is non-nullable.
        config_json="{}",           # default exists, set explicitly for determinism.
        display_name="Test Agent",
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


async def _seed_run(
    db: AsyncSession,
    *,
    agent_id: int,
    challenge_id: int = 1,
    completion_status: str | None = "complete",
    invalid_reason: str | None = None,
    provider_type: str = "hosted_instance",
    run_log_hash: str | None = "b" * 64,
) -> Run:
    run = Run(
        challenge_id=challenge_id,
        agent_id=agent_id,
        provider_type=provider_type,
        benchmark_wallet_address="SoLBenchxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        benchmark_wallet_ref="bw-1",
        status="completed",
        completion_status=completion_status,
        invalid_reason=invalid_reason,
        starting_value=1_000_000,
        ending_value=1_001_000,
        iterations_used=4,
        run_log_hash=run_log_hash,
        app_version="1.0.0",
        challenge_type="swap_execution",
        challenge_version="swap_execution_v1",
        action_schema_version="agent_action_v1",
        evidence_schema_version="evidence_v1",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


@pytest_asyncio.fixture
async def http_client(db: AsyncSession):
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Acceptance test — Task 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_v0_returns_404_for_unknown_run_id_via_http(http_client):
    resp = await http_client.get("/api/v1/verifier/runs/999999")
    assert resp.status_code == 404
    assert resp.json() == {"error": "run_not_found"}


@pytest.mark.asyncio
async def test_verifier_v0_returns_404_instance_unresolvable_via_http(
    db, http_client,
):
    """Bridge failure (Agent has no metadata_ref / privy_user_id) → 404 instance_unresolvable."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(db, template_id=template_id)
    agent = await _seed_bridge_agent(
        db,
        instance_id=instance.instance_id,
        use_metadata_ref=False,
        privy_user_id_override="bogus-not-a-bridge",
    )
    run = await _seed_run(db, agent_id=agent.agent_id)
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 404
    assert resp.json() == {"error": "instance_unresolvable"}


@pytest.mark.asyncio
async def test_verifier_v0_returns_422_for_completion_status_null_via_http(
    db, http_client,
):
    """Run still in progress (completion_status IS NULL) → 422 run_not_final."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(db, template_id=template_id)
    agent = await _seed_bridge_agent(db, instance_id=instance.instance_id)
    run = await _seed_run(
        db, agent_id=agent.agent_id, completion_status=None,
    )
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "run_not_final"
    assert "lifecycle_status" in body


@pytest.mark.asyncio
async def test_verifier_v0_v1_local_provider_runs_out_of_scope_via_http(
    db, http_client,
):
    """V1 local-provider runs are out of V0 scope → 422 unsupported_provider_type."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(db, template_id=template_id)
    agent = await _seed_bridge_agent(db, instance_id=instance.instance_id)
    run = await _seed_run(
        db, agent_id=agent.agent_id, provider_type="local",
    )
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 422
    assert resp.json() == {
        "error": "unsupported_provider_type",
        "provider_type": "local",
    }


@pytest.mark.asyncio
async def test_verifier_v0_external_custom_runtime_returns_422_defensively_via_http(
    db, http_client,
):
    """external_custom_runtime is reserved-only in V2; defensive 422."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="external_custom_runtime",
    )
    agent = await _seed_bridge_agent(db, instance_id=instance.instance_id)
    run = await _seed_run(db, agent_id=agent.agent_id)
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 422
    assert resp.json() == {
        "error": "unsupported_trust_label",
        "trust_label": "external_custom_runtime",
    }


@pytest.mark.asyncio
async def test_verifier_v0_non_live_instance_returns_404_instance_unresolvable_via_http(
    db, http_client,
):
    """A paused/torn-down instance must collapse to 404 instance_unresolvable.

    Locks the asymmetric-with-trust_label rule (spec §8): trust_label is a
    public contract enum so 422 is fine, but instance.status is operational
    so non-live cases collapse to the bridge-failure 404.
    """
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id, status="paused",
    )
    agent = await _seed_bridge_agent(db, instance_id=instance.instance_id)
    run = await _seed_run(db, agent_id=agent.agent_id)
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 404
    assert resp.json() == {"error": "instance_unresolvable"}


@pytest.mark.asyncio
async def test_verifier_v0_benchmarked_canonical_template_run_is_publicly_readable(
    db, http_client,
):
    """benchmarked_canonical_template runs are public — no Authorization header.

    Asserts: 200, verifier_version=="v0", run/lineage/evidence/cats blocks
    present, cats.wallet_safety equals compute_wallet_safety_cat output.
    """
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmarked_canonical_template",
        instance_owner_ref="platform-authority",
    )
    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="canonical_template",
    )
    run = await _seed_run(db, agent_id=agent.agent_id)

    # No bearer header — public read.
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["verifier_version"] == "v0"
    assert body["run"]["run_id"] == run.run_id
    assert body["run"]["completion_status"] == "complete"
    assert body["run"]["provider_type"] == "hosted_instance"

    assert body["lineage"]["instance_id"] == instance.instance_id
    assert body["lineage"]["trust_label"] == "benchmarked_canonical_template"
    assert body["lineage"]["subject_type"] == "canonical_template"
    assert body["lineage"]["template"]["template_key"] == "swap_executor_v1"

    assert body["evidence"]["run_log_hash"] == run.run_log_hash
    assert body["evidence"]["run_event_count"] == 0
    assert body["evidence"]["verification_artifacts"] == []

    expected_cat = await compute_wallet_safety_cat(db, run.run_id)
    assert body["cats"]["wallet_safety"] == expected_cat.model_dump(mode="json")


@pytest.mark.asyncio
async def test_verifier_v0_embeds_wallet_safety_cat_verbatim_via_compute(
    db, http_client,
):
    """cats.wallet_safety must be the byte-equivalent of compute_wallet_safety_cat.

    Locks the no-duplication discipline — the Verifier composes; never recomputes.
    Exercised here on a fail-verdict run so the embedded Cat carries non-trivial
    fields (reason, critique, failing checks).
    """
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmarked_canonical_template",
    )
    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="canonical_template",
    )
    run = await _seed_run(
        db, agent_id=agent.agent_id,
        invalid_reason="wallet_policy_rejected",
    )
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 200
    expected_cat = await compute_wallet_safety_cat(db, run.run_id)
    assert resp.json()["cats"]["wallet_safety"] == expected_cat.model_dump(mode="json")


from src.db.models import AgentTemplate as _AgentTemplate  # local alias for clarity


@pytest.mark.asyncio
async def test_verifier_v0_lineage_template_block_matches_agent_template_row(
    db, http_client,
):
    """lineage.template fields must equal the AgentTemplate row 1-to-1
    (template_version_at_deploy comes from AgentInstance, not AgentTemplate)."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmarked_canonical_template",
    )
    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="canonical_template",
    )
    run = await _seed_run(db, agent_id=agent.agent_id)
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 200
    template_block = resp.json()["lineage"]["template"]

    template_row = await db.get(_AgentTemplate, template_id)
    assert template_block["template_key"] == template_row.template_key
    assert template_block["template_version"] == template_row.template_version
    assert template_block["template_version_at_deploy"] == instance.template_version_at_deploy
    assert template_block["description"] == template_row.description
    assert template_block["is_deployable"] == bool(template_row.is_deployable)


from datetime import datetime, timezone
from src.db.models import VerificationArtifact


async def _seed_verification_artifact(
    db: AsyncSession,
    *,
    run_id: int,
    artifact_type: str,
    content_hash: str,
    uri_or_ref: str = "s3://internal-bucket/secret-path/blob.json",
) -> VerificationArtifact:
    artifact = VerificationArtifact(
        run_id=run_id,
        artifact_type=artifact_type,
        uri_or_ref=uri_or_ref,
        content_hash=content_hash,
        created_at=datetime.now(timezone.utc),
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    return artifact


@pytest.mark.asyncio
async def test_verifier_v0_evidence_block_includes_run_log_hash_and_artifact_metadata_only(
    db, http_client,
):
    """evidence.run_log_hash mirrors Run.run_log_hash; artifact entries
    expose only {artifact_id, artifact_type, content_hash, created_at}.
    uri_or_ref must NOT appear (private storage-layout)."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmarked_canonical_template",
    )
    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="canonical_template",
    )
    run = await _seed_run(db, agent_id=agent.agent_id)
    a1 = await _seed_verification_artifact(
        db, run_id=run.run_id,
        artifact_type="challenge_config",
        content_hash="c" * 64,
        uri_or_ref="s3://internal-bucket/MUST-NOT-LEAK.json",
    )
    a2 = await _seed_verification_artifact(
        db, run_id=run.run_id,
        artifact_type="settlement_record",
        content_hash="d" * 64,
    )

    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 200
    body = resp.json()

    assert body["evidence"]["run_log_hash"] == run.run_log_hash

    artifacts = body["evidence"]["verification_artifacts"]
    assert len(artifacts) == 2
    assert {a["artifact_id"] for a in artifacts} == {a1.artifact_id, a2.artifact_id}
    for entry in artifacts:
        assert set(entry.keys()) == {
            "artifact_id", "artifact_type", "content_hash", "created_at",
        }
        # Defense-in-depth: the private uri_or_ref string never appears.
        assert "MUST-NOT-LEAK" not in resp.text
        assert "uri_or_ref" not in entry


from src.db.models import RunEvent


async def _seed_run_event(
    db: AsyncSession,
    *,
    run_id: int,
    sequence_no: int,
    event_type: str,
    state_snapshot_json: str | None = None,
) -> RunEvent:
    event = RunEvent(
        run_id=run_id,
        sequence_no=sequence_no,
        event_type=event_type,
        timestamp=datetime.now(timezone.utc),
        state_snapshot_json=state_snapshot_json,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@pytest.mark.asyncio
async def test_verifier_v0_evidence_event_signals_are_aggregate_only(
    db, http_client,
):
    """evidence exposes run_event_count, last_event_sequence_no, last_event_type
    (mirrored as-is from RunEvent.event_type). Raw event payloads must NEVER
    appear in resp.text."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmarked_canonical_template",
    )
    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="canonical_template",
    )
    run = await _seed_run(db, agent_id=agent.agent_id)
    private_payload = "PRIVATE-STATE-MUST-NOT-LEAK"
    await _seed_run_event(
        db, run_id=run.run_id, sequence_no=1, event_type="observe",
        state_snapshot_json=f'{{"secret": "{private_payload}"}}',
    )
    await _seed_run_event(
        db, run_id=run.run_id, sequence_no=2, event_type="finalize",
    )

    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence"]["run_event_count"] == 2
    assert body["evidence"]["last_event_sequence_no"] == 2
    assert body["evidence"]["last_event_type"] == "finalize"

    # Raw payload must not leak.
    assert private_payload not in resp.text


class _FakeUser:
    def __init__(self, privy_user_id: str):
        self.privy_user_id = privy_user_id


@pytest.mark.asyncio
async def test_verifier_v0_benchmark_compatible_customized_instance_run_requires_owner_auth(
    db, http_client, monkeypatch,
):
    """3 sub-cases:
    1. No Authorization header → 401 (real get_current_user(None) raises;
       NOT monkey-patched, so end-to-end auth-layer behavior is exercised).
    2. Bearer present, wrong owner → 403 {"error": "not_instance_owner"}
       (monkeypatch.setattr on src.api.verifier.get_current_user).
    3. Bearer present, correct owner → 200 (monkeypatch.setattr replaced).
    """
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmark_compatible_customized_instance",
        instance_owner_ref="owner-real",
    )
    agent = await _seed_bridge_agent(db, instance_id=instance.instance_id)
    run = await _seed_run(db, agent_id=agent.agent_id)

    # ---- Case 1: no bearer → 401 from the real get_current_user(None). ----
    # NOT monkey-patched: this asserts the real auth-layer 401 propagates
    # via the route's `except HTTPException: raise` clause unmodified.
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 401, resp.text

    # ---- Case 2: bearer present, wrong owner → 403 ----
    async def _wrong_owner(_creds):
        return _FakeUser(privy_user_id="owner-wrong")

    monkeypatch.setattr("src.api.verifier.get_current_user", _wrong_owner)
    resp = await http_client.get(
        f"/api/v1/verifier/runs/{run.run_id}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 403
    assert resp.json() == {"error": "not_instance_owner"}

    # ---- Case 3: bearer present, correct owner → 200 ----
    # monkeypatch.setattr called again with the same target replaces the
    # previous patch; pytest still auto-reverts both at function teardown.
    async def _correct_owner(_creds):
        return _FakeUser(privy_user_id="owner-real")

    monkeypatch.setattr("src.api.verifier.get_current_user", _correct_owner)
    resp = await http_client.get(
        f"/api/v1/verifier/runs/{run.run_id}",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lineage"]["trust_label"] == "benchmark_compatible_customized_instance"


@pytest.mark.asyncio
async def test_verifier_v0_returns_500_internal_error_on_unexpected_exception(
    db, http_client, monkeypatch,
):
    """Unexpected exceptions must collapse to {"error": "internal_error"} with
    no internal exception text leaking. HTTPException remains exempt — that's
    tested in Task 10's Case 1 (401 propagates unmodified)."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmarked_canonical_template",
    )
    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="canonical_template",
    )
    run = await _seed_run(db, agent_id=agent.agent_id)

    secret = "INTERNAL-LEAKY-DETAIL-MUST-NOT-APPEAR"

    async def _boom(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(
        "src.api.verifier.build_verifier_run_response", _boom,
    )

    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 500
    assert resp.json() == {"error": "internal_error"}
    assert secret not in resp.text


@pytest.mark.asyncio
async def test_verifier_v0_response_does_not_expose_private_fields(
    db, http_client,
):
    """Sentinel-value grep audit. Every private field gets a unique sentinel
    string before seeding; resp.text must not contain any of them.

    Forbidden field set per spec §3.5 / §13:
      Run:           benchmark_wallet_address, benchmark_wallet_ref, score_inputs_json
      AgentInstance: instance_owner_ref (read for auth, never surfaced),
                     effective_config_json, runtime_handle_json,
                     wallet_address, hosted_wallet_ref, wallet_provider
      Agent:         system_prompt, config_json, owner_wallet, submission_hash
      VerificationArtifact: uri_or_ref (already covered in Task 8 — re-asserted here)

    Note: last_failure_reason is excluded from sentinel seeding because
    AgentInstance.last_failure_reason has a DB CHECK constraint limiting
    it to a fixed enum (provisioning_failed, wallet_created_runtime_failed,
    runtime_live_consent_failed). A free-text sentinel would raise an
    IntegrityError. The field is still blocked by the schema allowlist.
    """
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmarked_canonical_template",
        instance_owner_ref="SENTINEL-INSTANCE-OWNER-REF",
    )
    # Mutate private fields directly to ensure unique sentinel values.
    instance.effective_config_json = "SENTINEL-EFFECTIVE-CONFIG"
    instance.runtime_handle_json = "SENTINEL-RUNTIME-HANDLE"
    instance.wallet_address = "SENTINEL-WALLET-ADDR-INSTANCE"
    instance.hosted_wallet_ref = "SENTINEL-HOSTED-WALLET-REF"
    instance.wallet_provider = "SENTINEL-WALLET-PROVIDER"
    db.add(instance)
    await db.commit()

    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="canonical_template",
    )
    agent.system_prompt = "SENTINEL-SYSTEM-PROMPT"
    agent.config_json = "SENTINEL-AGENT-CONFIG"
    agent.owner_wallet = "SENTINEL-OWNER-WALLET"
    agent.submission_hash = "SENTINEL-SUBMISSION-HASH"
    db.add(agent)
    await db.commit()

    run = await _seed_run(db, agent_id=agent.agent_id)
    run.benchmark_wallet_address = "SENTINEL-BENCHMARK-WALLET-ADDR"
    run.benchmark_wallet_ref = "SENTINEL-BENCHMARK-WALLET-REF"
    run.score_inputs_json = "SENTINEL-SCORE-INPUTS"
    db.add(run)
    await db.commit()

    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 200, resp.text
    text = resp.text

    forbidden_sentinels = [
        "SENTINEL-INSTANCE-OWNER-REF",
        "SENTINEL-EFFECTIVE-CONFIG",
        "SENTINEL-RUNTIME-HANDLE",
        "SENTINEL-WALLET-ADDR-INSTANCE",
        "SENTINEL-HOSTED-WALLET-REF",
        "SENTINEL-WALLET-PROVIDER",
        "SENTINEL-SYSTEM-PROMPT",
        "SENTINEL-AGENT-CONFIG",
        "SENTINEL-OWNER-WALLET",
        "SENTINEL-SUBMISSION-HASH",
        "SENTINEL-BENCHMARK-WALLET-ADDR",
        "SENTINEL-BENCHMARK-WALLET-REF",
        "SENTINEL-SCORE-INPUTS",
    ]
    leaks = [s for s in forbidden_sentinels if s in text]
    assert leaks == [], (
        f"Private fields leaked into the Verifier response: {leaks}. "
        f"Add the field to the explicit allowlist exclusion or fix the "
        f"builder so it does not surface this column."
    )

    # Spec §10 lines 311-322 also require absence of literal private field-name
    # substrings. The sentinel-value check above catches a leak when the value
    # is non-null; these key-name checks catch the case where a future refactor
    # surfaces e.g. `"last_failure_reason": null` (no sentinel value to grep,
    # but the key itself leaks). Production code currently prevents this via
    # explicit Pydantic allowlists; this assertion locks the contract.
    forbidden_field_names = [
        "runtime_handle_json",
        "effective_config_json",
        "benchmark_wallet",
        "system_prompt",
        "config_json",
        "uri_or_ref",
        # RunEvent payload field names — must never appear in resp.text:
        "state_snapshot_json",
        "action_payload_json",
        "validation_payload_json",
        "execution_payload_json",
        "result_payload_json",
        "quote_snapshot_ref",
        "last_failure_reason",
    ]
    name_leaks = [s for s in forbidden_field_names if s in text]
    assert name_leaks == [], (
        f"Private field NAMES leaked into the Verifier response: {name_leaks}. "
        f"Even if the value is null/empty, the key string must not appear in "
        f"resp.text. Remove the field from the Verifier* Pydantic models in "
        f"schemas.py or stop the builder from constructing it."
    )


@pytest.mark.asyncio
async def test_verifier_v0_does_not_consult_agent_subject_type_for_auth(
    db, http_client,
):
    """Asymmetric lock: a customized-instance trust_label paired with a
    canonical_template subject_type must STILL require auth (anonymous → 401).
    Auth gate keys on AgentInstance.trust_label; Agent.subject_type is
    lineage metadata only and cannot relax the gate."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmark_compatible_customized_instance",
        instance_owner_ref="owner-real",
    )
    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="canonical_template",  # mismatch with trust_label
    )
    run = await _seed_run(db, agent_id=agent.agent_id)
    # No bearer header. Auth must still fire because trust_label says
    # "customized_instance" — subject_type is irrelevant to the gate.
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_verifier_v0_canonical_template_run_with_customized_instance_subject_type_is_publicly_readable(
    db, http_client,
):
    """Symmetric lock: same scenario, asserted from the public-readability angle.
    No 401, no 403 — just a 200, regardless of Agent.subject_type."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmarked_canonical_template",
    )
    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="customized_instance",
    )
    run = await _seed_run(db, agent_id=agent.agent_id)
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code != 401
    assert resp.status_code != 403
    assert resp.status_code == 200


from pathlib import Path

from sqlalchemy import func, select as _select

# RankSnapshot is required by spec §10's no-DB-writes count delta. The
# import lives in this Task 14 block (not the file's top-level import list)
# because earlier tasks didn't need it; keeping each task's added imports
# co-located with its code makes the per-task review surface smaller.
from src.db.models import RankSnapshot


@pytest.mark.asyncio
async def test_verifier_v0_no_db_writes_in_verifier_path(
    db, http_client,
):
    """The Verifier path is read-only. Row counts for every mutable table
    on the trust path must be unchanged across a successful 200 response.

    Per spec §10 the count set explicitly includes `rank_snapshots` — this
    is the lineage-not-score lock at the test layer (the Verifier must
    never mutate any leaderboard read model)."""
    template_id = await _seed_template(db)
    instance = await _seed_instance(
        db, template_id=template_id,
        trust_label="benchmarked_canonical_template",
    )
    agent = await _seed_bridge_agent(
        db, instance_id=instance.instance_id,
        subject_type="canonical_template",
    )
    run = await _seed_run(db, agent_id=agent.agent_id)

    async def _row_counts():
        return {
            "Run": (await db.execute(_select(func.count()).select_from(Run))).scalar_one(),
            "Agent": (await db.execute(_select(func.count()).select_from(Agent))).scalar_one(),
            "AgentInstance": (await db.execute(_select(func.count()).select_from(AgentInstance))).scalar_one(),
            "AgentTemplate": (await db.execute(_select(func.count()).select_from(AgentTemplate))).scalar_one(),
            "RunEvent": (await db.execute(_select(func.count()).select_from(RunEvent))).scalar_one(),
            "VerificationArtifact": (await db.execute(_select(func.count()).select_from(VerificationArtifact))).scalar_one(),
            "RankSnapshot": (await db.execute(_select(func.count()).select_from(RankSnapshot))).scalar_one(),
        }

    before = await _row_counts()
    resp = await http_client.get(f"/api/v1/verifier/runs/{run.run_id}")
    assert resp.status_code == 200
    after = await _row_counts()
    assert before == after, f"Verifier path mutated DB: before={before} after={after}"


def test_verifier_v0_no_llm_imports_in_trust_path():
    """Static guard: no LLM/network SDK imports anywhere in the Verifier modules.
    Same discipline as the Cat module."""
    forbidden_substrings = (
        "import anthropic",
        "import openai",
        "from anthropic",
        "from openai",
        "import agno",
        "from agno",
        "import litellm",
        "from litellm",
    )
    repo_root = Path(__file__).resolve().parents[2]
    files = [
        repo_root / "src" / "integrity" / "verifier" / "__init__.py",
        repo_root / "src" / "integrity" / "verifier" / "schemas.py",
        repo_root / "src" / "integrity" / "verifier" / "builder.py",
        repo_root / "src" / "api" / "verifier.py",
    ]
    leaks: list[tuple[str, str]] = []
    for path in files:
        text = path.read_text()
        for needle in forbidden_substrings:
            if needle in text:
                leaks.append((str(path), needle))
    assert leaks == [], f"LLM/network SDK imports found in trust path: {leaks}"


def test_verifier_v0_no_new_runinvalidreason_members():
    """The Verifier must not introduce new RunInvalidReason members.
    Reads the enum once at runtime; if a member is added by Verifier work,
    this test fires loudly."""
    from src.integrity.failure_taxonomy import RunInvalidReason

    expected_members = frozenset({
        # V1 baseline:
        "incomplete_required_actions",
        "invalid_action_attempts_exceeded",
        "stale_quote_execution_failed",
        "timeout_before_completion",
        "flattening_failed",
        "execution_error",
        # V2 hosted-path:
        "mainnet_guard_triggered",
        "wallet_policy_rejected",
        "runtime_invocation_failed",
        "authorization_signature_rejected",
        "hosted_wallet_unavailable",
    })
    actual = frozenset(m.value for m in RunInvalidReason)
    extra = actual - expected_members
    missing = expected_members - actual
    assert extra == set() and missing == set(), (
        f"RunInvalidReason drift: extra={extra}, missing={missing}. "
        f"Expected baseline lives in this test plus failure_taxonomy.py."
    )
