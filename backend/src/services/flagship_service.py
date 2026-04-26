"""FlagshipService — flagship identity bootstrap (Task 5 + Task 18).

Two layers, explicit split:

**Task 5 (agent layer)** — reserves the canonical flagship ``Agent`` row
with ``subject_type='canonical_template'`` and links
``AgentTemplate.benchmark_subject_agent_id`` to it. Methods:
``bootstrap_flagship``, ``get_flagship_agent``, ``ensure_flagship_exists``.

**Task 18 (instance layer)** — deploys the hosted flagship ``AgentInstance``
through the same ``InstanceService.deploy_instance(...)`` saga user
instances use, then promotes its ``trust_label`` to
``benchmarked_canonical_template``. Methods: ``deploy_flagship_instance``,
``get_flagship_instance``.

The two layers coexist: the canonical agent is the lineage reference
for benchmark history (`template_service.get_template_with_flagship_info`);
the hosted instance is the live flagship target for execution.

Hard boundaries:
- ``agents.trust_label`` does not exist; Task 18 never writes it.
- Task 18 never mutates ``agents`` or ``agent_templates.benchmark_subject_agent_id``.
- Task 5 never touches ``agent_instances``.
- Partial-failure instances from the saga stay at the default
  ``benchmark_compatible_customized_instance`` label — only the
  ``status='live'`` happy path gets the flagship trust-label promotion.

See ``.taskmaster/docs/task5-edge-case-spec.md`` and
``.taskmaster/docs/task18-edge-case-spec.md``.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Agent, AgentInstance, AgentTemplate, Run

if TYPE_CHECKING:  # pragma: no cover — imports for typing only
    from src.services.instance_service import InstanceService

# Sentinel platform identity for the reserved canonical flagship agent.
# Not a real Solana pubkey — a clear, 44-char non-base58 placeholder that
# is easy to spot during DB inspection.
_PLATFORM_PRIVY_USER_ID: str = "platform-authority"
_PLATFORM_SENTINEL_WALLET: str = "1" * 44  # 44 chars, matches agents.owner_wallet column
_FLAGSHIP_DISPLAY_NAME: str = "Flagship Swap Executor"

# Task 18 — identity of the hosted flagship instance.
_FLAGSHIP_INSTANCE_OWNER_REF: str = "platform:flagship"
_FLAGSHIP_TRUST_LABEL: str = "benchmarked_canonical_template"
# All-True platform consent — the platform acknowledges its own
# devnet-only hosted execution on behalf of the flagship deploy.
_PLATFORM_CONSENT: dict = {
    "devnet_only_acknowledged": True,
    "platform_managed_signing_acknowledged": True,
    "spend_caps_acknowledged": True,
    "no_indemnity_acknowledged": True,
}


class FlagshipServiceError(Exception):
    """Raised when flagship-agent bootstrap cannot proceed.

    Local to this service. Not overloaded onto Task 13/14's saga
    taxonomy or Task 15's ``InvalidInstanceStateError``.
    """


class FlagshipService:
    """Flagship identity — agent-layer (Task 5) and instance-layer (Task 18).

    One instance per request/caller. Agent-layer methods require only
    the ``AsyncSession``. Instance-layer methods additionally require
    an injected ``InstanceService``; calling them without one raises
    ``FlagshipServiceError``.
    """

    def __init__(
        self,
        db: AsyncSession,
        instance_service: "InstanceService | None" = None,
    ) -> None:
        self.db = db
        self.instance_service = instance_service

    # ------------------------------------------------------------------
    # bootstrap_flagship — idempotent canonical agent creation
    # ------------------------------------------------------------------

    async def bootstrap_flagship(
        self, template_key: str = "swap_executor_v1"
    ) -> Agent:
        """Ensure the canonical flagship ``Agent`` exists and is linked.

        Idempotent: if ``template.benchmark_subject_agent_id`` is
        already set to an existing agent, that agent is returned.
        Otherwise a new canonical agent is created and the template FK
        is updated in the same transaction.

        Raises:
            FlagshipServiceError: the template does not exist.
        """
        template = await self._get_template(template_key)
        if template is None:
            raise FlagshipServiceError(
                f"Template {template_key!r} not found"
            )

        # Idempotency guard: template FK already points at an agent row.
        if template.benchmark_subject_agent_id is not None:
            existing = await self.db.get(
                Agent, template.benchmark_subject_agent_id
            )
            if existing is not None:
                return existing
            # FK set but target row missing — treat as unlinked and
            # re-create below.

        agent = Agent(
            privy_user_id=_PLATFORM_PRIVY_USER_ID,
            owner_wallet=_PLATFORM_SENTINEL_WALLET,
            display_name=_FLAGSHIP_DISPLAY_NAME,
            submission_type="canonical_template",
            submission_hash=_canonical_submission_hash(template_key),
            system_prompt=template.system_prompt,
            config_json=template.default_config_json,
            subject_type="canonical_template",
            status="active",
            moderation_status="active",
        )
        self.db.add(agent)
        await self.db.flush()

        template.benchmark_subject_agent_id = agent.agent_id
        await self.db.commit()
        return agent

    # ------------------------------------------------------------------
    # get_flagship_agent — point-read via template FK
    # ------------------------------------------------------------------

    async def get_flagship_agent(
        self, template_key: str = "swap_executor_v1"
    ) -> Optional[Agent]:
        """Return the canonical flagship Agent linked to ``template_key``.

        Returns ``None`` if the template doesn't exist or hasn't been
        bootstrapped (``benchmark_subject_agent_id`` unset).
        """
        template = await self._get_template(template_key)
        if template is None:
            return None
        if template.benchmark_subject_agent_id is None:
            return None
        return await self.db.get(Agent, template.benchmark_subject_agent_id)

    # ------------------------------------------------------------------
    # ensure_flagship_exists — get-or-create convenience
    # ------------------------------------------------------------------

    async def ensure_flagship_exists(
        self, template_key: str = "swap_executor_v1"
    ) -> Agent:
        """Return the canonical flagship Agent, creating it if missing.

        Convenience wrapper for Task 19 cron / Task 20 flagship API
        consumers that want "give me the canonical agent, bootstrapping
        on first use."
        """
        existing = await self.get_flagship_agent(template_key)
        if existing is not None:
            return existing
        return await self.bootstrap_flagship(template_key)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_template(self, template_key: str) -> Optional[AgentTemplate]:
        result = await self.db.execute(
            select(AgentTemplate).where(
                AgentTemplate.template_key == template_key
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Task 18 — hosted flagship instance layer
    # ------------------------------------------------------------------

    async def deploy_flagship_instance(
        self, template_key: str = "swap_executor_v1"
    ) -> AgentInstance:
        """Deploy (or return existing) the hosted flagship ``AgentInstance``.

        Runs through the same ``InstanceService.deploy_instance(...)``
        saga user instances use, then promotes the resulting row's
        ``trust_label`` to ``benchmarked_canonical_template`` on the
        happy path.

        Idempotent: if a live non-superseded flagship instance already
        exists for the template, it is returned unchanged. Non-live or
        superseded prior rows are ignored — a fresh live flagship is
        deployed. Operator repair (Task 14) owns cleanup of stale rows.

        Preconditions (fail-fast — no self-heal):
        - ``instance_service`` was injected at construction time.
        - Template exists.
        - Task 5 canonical lineage is in place:
          ``template.benchmark_subject_agent_id`` points to an existing
          ``Agent`` row.

        On partial-failure saga states (``wallet_created_runtime_failed``,
        ``runtime_live_consent_failed``, ``provisioning_failed``) the
        returned row carries the default
        ``benchmark_compatible_customized_instance`` label — the
        flagship trust-label promotion happens only when
        ``status == "live"``.

        Raises:
            FlagshipServiceError: missing instance_service, missing
                template, or missing/stale Task 5 lineage.
        """
        if self.instance_service is None:
            raise FlagshipServiceError(
                "InstanceService required for deploy_flagship_instance; "
                "construct FlagshipService(db, instance_service=...) "
                "for Task 18 operations."
            )

        template = await self._get_template(template_key)
        if template is None:
            raise FlagshipServiceError(
                f"Template {template_key!r} not found"
            )

        # Task 5 lineage precondition — fail-fast.
        if template.benchmark_subject_agent_id is None:
            raise FlagshipServiceError(
                f"canonical flagship not reserved for template "
                f"{template_key!r} (benchmark_subject_agent_id is unset); "
                f"run Task 5 bootstrap_flagship first"
            )
        canonical_agent = await self.db.get(
            Agent, template.benchmark_subject_agent_id
        )
        if canonical_agent is None:
            raise FlagshipServiceError(
                f"canonical flagship FK is stale for template "
                f"{template_key!r} (agent_id="
                f"{template.benchmark_subject_agent_id} not found); "
                f"repair Task 5 linkage before re-deploy"
            )

        # Idempotency — return an existing live flagship if present.
        existing = await self.get_flagship_instance(template_key)
        if existing is not None:
            return existing

        effective_config = json.loads(template.default_config_json)
        instance = await self.instance_service.deploy_instance(
            template_key=template_key,
            effective_config=effective_config,
            consent=dict(_PLATFORM_CONSENT),
            owner_ref=_FLAGSHIP_INSTANCE_OWNER_REF,
        )

        # Trust-label promotion only on happy path. Partial-failure rows
        # stay at the default label and are left for operator repair.
        if instance.status == "live":
            instance.trust_label = _FLAGSHIP_TRUST_LABEL
            await self.db.commit()

        return instance

    async def get_flagship_runs(
        self, instance_id: int, limit: int = 30
    ) -> list[Run]:
        """Return recent ``Run`` rows attached to the flagship, newest first.

        Task 20 read path. Runs are attached via Task 15's synthetic
        instance→agent mapping (``agents.privy_user_id =
        'instance:{instance_id}'`` + ``subject_type='customized_instance'``).
        Unfiltered by status or completion_status — the caller's public
        page renders pending/invalid/failed/complete rows together per
        the V2 spec §7 "nothing filtered, nothing staged" anchor.
        """
        synthetic_key = f"instance:{instance_id}"
        result = await self.db.execute(
            select(Run)
            .join(Agent, Run.agent_id == Agent.agent_id)
            .where(
                Agent.privy_user_id == synthetic_key,
                Agent.subject_type == "customized_instance",
            )
            .order_by(Run.created_at.desc(), Run.run_id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_flagship_instance(
        self, template_key: str = "swap_executor_v1"
    ) -> Optional[AgentInstance]:
        """Return the current live flagship instance for ``template_key``.

        Filters: ``instance_owner_ref='platform:flagship'``,
        ``trust_label='benchmarked_canonical_template'``,
        ``status='live'``, ``superseded_by_instance_id IS NULL``,
        ``template_id`` resolved from ``template_key``. Orders by
        ``created_at DESC`` + ``instance_id DESC`` as tie-breaker and
        returns the first match.

        Returns ``None`` if the template doesn't exist or no matching
        instance is found.
        """
        template = await self._get_template(template_key)
        if template is None:
            return None
        result = await self.db.execute(
            select(AgentInstance)
            .where(
                AgentInstance.instance_owner_ref == _FLAGSHIP_INSTANCE_OWNER_REF,
                AgentInstance.trust_label == _FLAGSHIP_TRUST_LABEL,
                AgentInstance.status == "live",
                AgentInstance.superseded_by_instance_id.is_(None),
                AgentInstance.template_id == template.template_id,
            )
            .order_by(
                AgentInstance.created_at.desc(),
                AgentInstance.instance_id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


def compute_outcome_distribution(runs: list[Run]) -> dict:
    """Bucket runs into complete/invalid/failed/pending, mutually exclusive.

    Mapping (priority order, see ``.taskmaster/docs/task20-edge-case-spec.md`` §6):

    - ``completion_status == "complete"`` → **complete**
    - ``completion_status in ("invalid", "incomplete")`` → **invalid**
      (``incomplete`` folds into ``invalid`` at the display boundary)
    - ``status in ("failed", "timeout", "onchain_failed")`` → **failed**
    - ``status in ("pending", "pending_onchain", "running")`` → **pending**
    - anything else → counted in ``total`` only (no named bucket)

    Returns per-bucket counts + percentages + total. Zero-division safe.
    """
    total = len(runs)
    buckets = {"complete": 0, "invalid": 0, "failed": 0, "pending": 0}
    for r in runs:
        cs = getattr(r, "completion_status", None)
        st = getattr(r, "status", None)
        if cs == "complete":
            buckets["complete"] += 1
        elif cs in ("invalid", "incomplete"):
            buckets["invalid"] += 1
        elif st in ("failed", "timeout", "onchain_failed"):
            buckets["failed"] += 1
        elif st in ("pending", "pending_onchain", "running"):
            buckets["pending"] += 1
        # else: uncounted, but still contributes to total
    def pct(n: int) -> float:
        return 0.0 if total == 0 else 100.0 * n / total

    return {
        "complete_count": buckets["complete"],
        "complete_pct": pct(buckets["complete"]),
        "invalid_count": buckets["invalid"],
        "invalid_pct": pct(buckets["invalid"]),
        "failed_count": buckets["failed"],
        "failed_pct": pct(buckets["failed"]),
        "pending_count": buckets["pending"],
        "total": total,
    }


def _canonical_submission_hash(template_key: str) -> str:
    """Deterministic submission_hash for the canonical flagship agent.

    ``sha256("canonical-template:{template_key}")``. Deterministic so
    repeated bootstrap attempts hash identically; distinct from user
    submission hashes because the ``canonical-template:`` prefix
    identifies the role.
    """
    return hashlib.sha256(
        f"canonical-template:{template_key}".encode("utf-8")
    ).hexdigest()
