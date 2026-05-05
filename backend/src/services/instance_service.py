"""InstanceService — V2 hosted-instance deploy saga.

Owns the 6-step deploy saga that turns a (template_key, effective_config,
consent, owner_ref) tuple into an ``agent_instances`` row under the
Phase-0-locked Privy agentic-wallet posture and the Task 12 session-based
AgentOS runtime contract.

Step overview (see ``.taskmaster/docs/task13-edge-case-spec.md``):

    1. ``policy_engine.validate_spec(effective_config)``
    2. ``policy_engine.build_wallet_policy(spec, ORCA_DEVNET_ALLOWLIST, chain="devnet")``
    3. ``wallet_service.create_hosted_wallet(policy_id, authorization_pubkey)``
    4. Insert ``AgentInstance`` row with ``status='provisioning'``
    5. ``runtime.deploy(spec)`` → persist ``runtime_handle_json``
    6. ``policy_engine.record_consent(consent)`` → ``VerificationArtifact``
       → link ``consent_artifact_id`` → ``status='live'``

Failure taxonomy (Task 2 contract):

- Steps 1/2/3/4-template-resolve: raise ``InstanceDeployError`` with
  ``SagaFailureReason.PROVISIONING_FAILED.value``. No row persisted.
- Step 5 failure: row committed with ``status='wallet_created_runtime_failed'``
  and ``last_failure_reason='wallet_created_runtime_failed'``. Raw diagnostics
  go to logs, never to ``last_failure_reason``.
- Step 6 failure: row committed with ``status='runtime_live_consent_failed'``
  and ``last_failure_reason='runtime_live_consent_failed'``. Same rule.

Conflict-resolution notes:

- ``VerificationArtifact.run_id`` is nullable as of Alembic migration
  ``f8b2a1c3d4e5``; deploy-time consent rows leave it NULL and store the
  canonical JSON inline in ``uri_or_ref``.
- ``wallet_service.create_hosted_wallet`` (shipped in Task 9) takes a
  pre-existing Privy ``policy_id`` string + a base64-DER P-256 SPKI
  public key. Those two values are injected through ``InstanceService``'s
  constructor so production wiring reads them from config and tests can
  supply them directly.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AgentInstance, AgentTemplate, VerificationArtifact
from src.integrity.failure_taxonomy import SagaFailureReason
from src.integrity.saga_statuses import SagaStatus
from src.policy.allowlists import ORCA_DEVNET_ALLOWLIST
from src.policy.engine import InstancePolicyEngine, PolicyEngineError, validate_spec_for_template
from src.runtime.base import InstanceHandle, InstanceRuntime, InstanceSpec
from src.services.wallet_service import (
    ChainMismatchError,
    PrivyAPIError,
    WalletService,
)

logger = logging.getLogger(__name__)


class InstanceDeployError(Exception):
    """Raised when the deploy saga fails before any row is written.

    Carries a ``SagaFailureReason`` taxonomy value on ``status`` and a raw
    diagnostic on ``details``. Consumers render ``status`` via the shared
    failure-taxonomy copy map; ``details`` is for logs/operator surfaces
    only — never persisted to the DB.
    """

    def __init__(self, status: str, details: str) -> None:
        self.status = status
        self.details = details
        super().__init__(f"Deploy failed ({status}): {details}")


class InstanceService:
    """Implements the V2 deploy saga for hosted instances."""

    def __init__(
        self,
        db: AsyncSession,
        policy_engine: InstancePolicyEngine,
        wallet_service: "WalletService | Any",
        runtime: "InstanceRuntime | Any",
        *,
        hosted_wallet_policy_id: str,
        authorization_pubkey: str,
    ) -> None:
        if not hosted_wallet_policy_id:
            raise ValueError(
                "InstanceService: hosted_wallet_policy_id must be non-empty "
                "(pre-existing Privy policy id, see Task 9 create_hosted_wallet)."
            )
        if not authorization_pubkey:
            raise ValueError(
                "InstanceService: authorization_pubkey must be non-empty "
                "(base64-DER P-256 SPKI of the Proof Arena authorization key)."
            )
        self.db = db
        self.policy_engine = policy_engine
        self.wallet_service = wallet_service
        self.runtime = runtime
        self.hosted_wallet_policy_id = hosted_wallet_policy_id
        self.authorization_pubkey = authorization_pubkey

    # ------------------------------------------------------------------
    # deploy_instance — the saga
    # ------------------------------------------------------------------

    async def deploy_instance(
        self,
        *,
        template_key: str,
        effective_config: dict[str, Any],
        consent: dict[str, Any],
        owner_ref: str,
    ) -> AgentInstance:
        """Run the 6-step deploy saga. Returns the resulting ``AgentInstance``.

        On pre-row failures (steps 1-3 and step-4 template resolution) the
        saga raises ``InstanceDeployError`` and no DB row is written. On
        post-wallet failures the saga commits a partial row in the matching
        ``*_failed`` saga state and returns it so callers can inspect and
        route to operator repair (Task 14).
        """
        # Step 0 — owner_ref length guard (Task 41 fixpack F2). Defense
        # in depth: `get_current_user` already returns a bounded identity
        # ≤128 chars (F1), but any future caller bypassing F1 still gets
        # a controlled failure here instead of a raw asyncpg
        # `StringDataRightTruncationError` 500 from the INSERT.
        # `agent_instances.instance_owner_ref` is `varchar(128)`.
        if len(owner_ref) > 128:
            raise InstanceDeployError(
                SagaFailureReason.PROVISIONING_FAILED.value,
                f"owner_ref length {len(owner_ref)} exceeds 128-char limit",
            )

        # Step 1 — template-aware envelope validation (spec §5.2 round-3 lock).
        if template_key == "swap_executor_v1":
            validation = self.policy_engine.validate_spec(effective_config)
        else:
            validation = validate_spec_for_template(template_key, effective_config)
        if not validation.ok:
            raise InstanceDeployError(
                SagaFailureReason.PROVISIONING_FAILED.value,
                "; ".join(validation.errors),
            )

        # Step 2 — build wallet policy ONLY for swap (rebalance V0 reuses the wallet
        # created at swap-deploy time under the Phase-0 ORCA devnet allowlist).
        if template_key == "swap_executor_v1":
            try:
                self.policy_engine.build_wallet_policy(
                    spec=effective_config,
                    allowlist_profile=ORCA_DEVNET_ALLOWLIST,
                    chain="devnet",
                )
            except PolicyEngineError as exc:
                raise InstanceDeployError(
                    SagaFailureReason.PROVISIONING_FAILED.value,
                    str(exc),
                ) from exc

        # Step 3 — create hosted wallet. The policy_id points at a
        # pre-existing Privy policy created out of band during Phase 0; the
        # wallet_policy dict from step 2 is defense-in-depth evidence that
        # our local view of the policy matches the Phase-0 profile.
        try:
            wallet = await self.wallet_service.create_hosted_wallet(
                policy_id=self.hosted_wallet_policy_id,
                authorization_pubkey=self.authorization_pubkey,
            )
        except (PrivyAPIError, ChainMismatchError) as exc:
            raise InstanceDeployError(
                SagaFailureReason.PROVISIONING_FAILED.value,
                str(exc),
            ) from exc

        # Step 4 — template resolution + row insert. Template lookup must
        # happen *after* wallet creation because wallet_service failures
        # should not leave orphaned template reads (no state either way,
        # but the error shape is clearer this order).
        try:
            template = await self._resolve_template(template_key)
        except InstanceDeployError:
            # Propagate — wallet already exists at this point, but no
            # agent_instances row is written. Operator-tooling reconciliation
            # is handled in Task 14.
            raise

        instance = AgentInstance(
            template_id=template.template_id,
            template_version_at_deploy=template.template_version,
            instance_owner_ref=owner_ref,
            effective_config_json=json.dumps(effective_config, sort_keys=True),
            wallet_address=wallet["address"],
            hosted_wallet_ref=wallet["id"],
            wallet_provider="privy",
            status=SagaStatus.PROVISIONING.value,
        )
        self.db.add(instance)
        await self.db.flush()

        # Step 5 — runtime deploy (AgentOS session creation per Task 12).
        try:
            spec = self._build_runtime_spec(template, effective_config, owner_ref)
            handle = await self.runtime.deploy(spec)
            instance.runtime_handle_json = json.dumps(asdict(handle))
        except Exception:  # noqa: BLE001 — translated to saga state
            logger.exception(
                "InstanceService.deploy_instance: runtime deploy failed "
                "(instance_id=%s)",
                instance.instance_id,
            )
            instance.status = SagaStatus.WALLET_CREATED_RUNTIME_FAILED.value
            instance.last_failure_reason = (
                SagaFailureReason.WALLET_CREATED_RUNTIME_FAILED.value
            )
            await self.db.commit()
            return instance

        # Step 6 — record consent + VerificationArtifact + status=live.
        try:
            consent_record = self.policy_engine.record_consent(consent)
            artifact = VerificationArtifact(
                run_id=None,  # Deploy-time: no run yet (Alembic f8b2a1c3d4e5).
                artifact_type="deployment_consent",
                uri_or_ref=consent_record.canonical_json,
                content_hash=consent_record.content_hash,
            )
            self.db.add(artifact)
            await self.db.flush()
            instance.consent_artifact_id = artifact.artifact_id
            instance.status = SagaStatus.LIVE.value
            instance.last_failure_reason = None
        except Exception:  # noqa: BLE001 — translated to saga state
            logger.exception(
                "InstanceService.deploy_instance: consent write failed "
                "(instance_id=%s)",
                instance.instance_id,
            )
            instance.status = SagaStatus.RUNTIME_LIVE_CONSENT_FAILED.value
            instance.last_failure_reason = (
                SagaFailureReason.RUNTIME_LIVE_CONSENT_FAILED.value
            )

        await self.db.commit()
        return instance

    # ------------------------------------------------------------------
    # Helpers — template resolution + runtime spec build
    # ------------------------------------------------------------------

    async def _resolve_template(self, template_key: str) -> AgentTemplate:
        result = await self.db.execute(
            select(AgentTemplate).where(
                AgentTemplate.template_key == template_key
            )
        )
        template = result.scalar_one_or_none()
        if template is None:
            raise InstanceDeployError(
                SagaFailureReason.PROVISIONING_FAILED.value,
                f"unknown template_key {template_key!r}",
            )
        # is_deployable is stored as Integer (0/1) per model comment.
        if not template.is_deployable:
            raise InstanceDeployError(
                SagaFailureReason.PROVISIONING_FAILED.value,
                f"template {template_key!r} is not deployable (is_deployable=0)",
            )
        return template

    @staticmethod
    def _build_runtime_spec(
        template: AgentTemplate,
        effective_config: dict[str, Any],
        owner_ref: str,
    ) -> InstanceSpec:
        return InstanceSpec(
            template_key=template.template_key,
            template_version=template.template_version,
            effective_config=effective_config,
            instance_owner_ref=owner_ref,
        )

    # ------------------------------------------------------------------
    # update_instance_config — Task 28 versioned instance records
    # ------------------------------------------------------------------

    async def update_instance_config(
        self,
        instance_id: int,
        new_config: dict[str, Any],
        consent: dict[str, Any],
    ) -> AgentInstance:
        """Config change → new ``AgentInstance`` row, old row frozen via FK.

        Contract (see ``.taskmaster/docs/task28-edge-case-spec.md``):

        - Unchanged config is a no-op: returns the old row; no new row
          is created.
        - Changed config reuses ``deploy_instance(...)`` to create a
          fresh row inheriting ``template_key`` + ``instance_owner_ref``
          from the old row.
        - Supersession is recorded as a single FK write on the old row
          (``old.superseded_by_instance_id = new.instance_id``). The
          old row's ``status`` column is NOT mutated — the locked
          SagaStatus enum does not include ``superseded`` and the
          CHECK constraint would reject it.
        - A new row that fails the deploy saga (``*_failed`` status)
          does NOT supersede the old row; the failed row is returned
          to the caller for operator repair.
        - Updating an already-superseded source row is rejected —
          callers must update the current head of the chain.
        """
        old_instance = await self.db.get(AgentInstance, instance_id)
        if old_instance is None:
            raise ValueError(f"Instance {instance_id} not found")
        if old_instance.superseded_by_instance_id is not None:
            raise ValueError(
                f"Instance {instance_id} is already superseded by "
                f"{old_instance.superseded_by_instance_id}; "
                "call update_instance_config on the current head of the chain"
            )

        old_config = json.loads(old_instance.effective_config_json)
        if new_config == old_config:
            return old_instance

        template = await self.db.get(AgentTemplate, old_instance.template_id)
        if template is None:
            raise ValueError(
                f"Template {old_instance.template_id} for instance "
                f"{instance_id} not found"
            )

        new_instance = await self.deploy_instance(
            template_key=template.template_key,
            effective_config=new_config,
            consent=consent,
            owner_ref=old_instance.instance_owner_ref,
        )

        if new_instance.status == SagaStatus.LIVE.value:
            old_instance.superseded_by_instance_id = new_instance.instance_id
            await self.db.commit()

        return new_instance

    # ------------------------------------------------------------------
    # Reads — consumed by instance dashboard + operator endpoints (Task 14)
    # ------------------------------------------------------------------

    async def get_instance_by_id(self, instance_id: int) -> Optional[AgentInstance]:
        result = await self.db.execute(
            select(AgentInstance).where(
                AgentInstance.instance_id == instance_id
            )
        )
        return result.scalar_one_or_none()

    async def get_instances_by_owner(
        self, owner_ref: str
    ) -> list[AgentInstance]:
        result = await self.db.execute(
            select(AgentInstance)
            .where(AgentInstance.instance_owner_ref == owner_ref)
            .order_by(
                AgentInstance.created_at.desc(),
                AgentInstance.instance_id.desc(),
            )
        )
        return list(result.scalars().all())

    async def get_instances_by_status(
        self, status_list: Iterable[Any]
    ) -> list[AgentInstance]:
        # Accept enum members or raw strings uniformly.
        values: list[str] = []
        for s in status_list:
            if isinstance(s, SagaStatus):
                values.append(s.value)
            else:
                values.append(str(s))
        if not values:
            return []
        result = await self.db.execute(
            select(AgentInstance)
            .where(AgentInstance.status.in_(values))
            .order_by(
                AgentInstance.created_at.desc(),
                AgentInstance.instance_id.desc(),
            )
        )
        return list(result.scalars().all())
