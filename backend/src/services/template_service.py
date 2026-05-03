"""TemplateService — V2 canonical template catalog.

Service layer for the off-chain ``agent_templates`` table. Owns registration
(envelope-locked), point reads, catalog listing, and a detail read that
surfaces flagship trust-label lineage when available.

Boundary rules (V2 spec §9, §10 + task-tree cleanup invariants):

- **Zero on-chain work.** Templates live off-chain only.
- **Envelope lock.** ``allowed_fields_json`` must match the envelope set for
  the template's ``template_key`` per ``TEMPLATE_ENVELOPE_REGISTRY`` in
  ``policy/engine.py``. Swap registrations resolve to the V2 5-field envelope;
  rebalance registrations resolve to the V0 7-field envelope. Any drift is
  rejected at registration time via ``_validate_allowed_fields_for_template``.
- **Trust-label source of truth.** ``get_template_with_flagship_info`` reads
  the flagship trust label from ``agent_instances.trust_label`` (filtered to
  the live flagship instance for the template). ``Agent`` has no
  ``trust_label`` column — ``subject_type`` is the agent-layer marker.
- **Immutable catalog.** No update or delete methods. New templates register
  as new rows; a superseding version registers under a new ``template_key``.
- **No benchmark overclaim.** Template-layer responses never surface
  benchmark scores — only lineage via the flagship trust label.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Agent, AgentInstance, AgentTemplate
from src.integrity.trust_labels import TrustLabel
from src.policy.engine import (
    InstancePolicyEngine,
    _ALLOWED_ENVELOPE_FIELDS,
    TEMPLATE_ENVELOPE_REGISTRY,
    validate_spec_for_template,
)


class TemplateServiceError(Exception):
    """Base class for TemplateService failures."""


class TemplateValidationError(TemplateServiceError):
    """Raised when a template registration fails V2 envelope validation."""


class TemplateAlreadyExistsError(TemplateServiceError):
    """Raised when a template_key collides with an existing row."""


# Locked flagship trust label — sourced from the V2 trust-label contract
# (Task 6 / A-5). See plan §10 invariant 12 and cleanup-pass resolution
# across tasks 20.1, 28, 33.
_FLAGSHIP_TRUST_LABEL: str = TrustLabel.BENCHMARKED_CANONICAL_TEMPLATE.value


# Canonical V2 seed for the ``swap_executor_v1`` template. The system prompt
# is BALANCED from frontend ``StrategyBuilderLite.tsx`` verbatim — that is
# the V1 content V2 evolves from per the spec §7 "V2 Template Registry
# evolves from Strategy Builder Lite". The default config uses the V2
# 5-field envelope (BALANCED's V1 config had risk_level / prefer_stable_routes
# keys that are not V2 envelope fields).
SWAP_EXECUTOR_V1_SEED: dict[str, Any] = {
    "template_key": "swap_executor_v1",
    "template_version": "swap_executor_v1",
    "description": (
        "Execute a fixed-basket swap on Solana devnet under balanced risk "
        "controls."
    ),
    "allowed_fields_json": json.dumps(sorted(_ALLOWED_ENVELOPE_FIELDS)),
    "default_config_json": json.dumps(
        {
            "allowed_token_universe": [
                "So11111111111111111111111111111111111111112",
                "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k",
            ],
            "max_slippage_bps": 100,
            "max_position_size": 1_000_000,
            "max_iterations": 10,
            "max_runtime_seconds": 180,
        }
    ),
    "system_prompt": (
        "Balance risk and opportunity. Use moderate slippage tolerance. "
        "Complete the required basket while avoiding unnecessary invalid "
        "actions or excessive waiting."
    ),
    "is_deployable": True,
}

# Rebalance fields: frozenset from TEMPLATE_ENVELOPE_REGISTRY for convenience.
_REBALANCE_ENVELOPE_FIELDS = TEMPLATE_ENVELOPE_REGISTRY["rebalance_executor_v1"]

# Canonical seed for the ``rebalance_executor_v1`` template (V0 Cat).
REBALANCE_EXECUTOR_V1_SEED: dict[str, Any] = {
    "template_key": "rebalance_executor_v1",
    "template_version": "rebalance_executor_v1",
    "description": (
        "Rebalance a Solana token portfolio on devnet toward target allocations."
    ),
    "allowed_fields_json": json.dumps(sorted(_REBALANCE_ENVELOPE_FIELDS)),
    "default_config_json": json.dumps(
        {
            "allowed_token_universe": [
                "So11111111111111111111111111111111111111112",
                "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k",
            ],
            "target_allocations": {
                "So11111111111111111111111111111111111111112": 0.5,
                "BRjpCHtyQLNCo8gqRUr8jtdAj5AjPYQaoqbvcZiHok1k": 0.5,
            },
            "rebalance_threshold_bps": 100,
            "max_slippage_bps": 100,
            "max_position_weight": 1.0,
            "max_trade_value": 1_000_000,
            "dry_run": False,
        }
    ),
    "system_prompt": (
        "Rebalance the portfolio toward the target allocations using minimal "
        "trades and conservative slippage controls."
    ),
    "is_deployable": True,
}


def _validate_allowed_fields_for_template(
    template_key: str,
    allowed_fields_json: str,
) -> None:
    """Template-aware allowed-fields validator (per spec §5.2 + plan Task 2).

    Mirrors deploy-time validation (``policy.engine.validate_spec_for_template``)
    at template-registration time so a malformed seed cannot enter the DB.
    """
    if not isinstance(template_key, str) or template_key not in TEMPLATE_ENVELOPE_REGISTRY:
        raise TemplateValidationError(
            f"unknown template_key {template_key!r} at registration; "
            f"must be one of {sorted(TEMPLATE_ENVELOPE_REGISTRY.keys())}"
        )
    try:
        decoded = json.loads(allowed_fields_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise TemplateValidationError(
            f"allowed_fields_json must be a JSON array of strings; "
            f"got error: {exc}"
        ) from exc
    if not isinstance(decoded, list):
        raise TemplateValidationError(
            f"allowed_fields_json must decode to a JSON array; "
            f"got {type(decoded).__name__}"
        )
    provided = set(decoded)
    expected = set(TEMPLATE_ENVELOPE_REGISTRY[template_key])
    missing = expected - provided
    extra = provided - expected
    if missing or extra:
        raise TemplateValidationError(
            f"allowed_fields_json mismatch for template_key={template_key!r}; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )


class TemplateService:
    """Manages the V2 canonical template catalog."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.policy_engine = InstancePolicyEngine()

    # ------------------------------------------------------------------
    # register_template
    # ------------------------------------------------------------------
    async def register_template(
        self,
        *,
        template_key: str,
        template_version: str,
        description: str,
        allowed_fields_json: str,
        default_config_json: str,
        system_prompt: str,
        is_deployable: bool = True,
        benchmark_subject_agent_id: Optional[int] = None,
    ) -> AgentTemplate:
        """Register a new canonical template with strict template-aware envelope validation.

        ``allowed_fields_json`` is checked against ``TEMPLATE_ENVELOPE_REGISTRY``
        for the given ``template_key`` (swap → V2 5-field envelope; rebalance →
        V0 7-field envelope). ``default_config_json`` is then validated by
        ``policy.engine.validate_spec_for_template`` for the same key.

        Raises:
            TemplateValidationError: unknown ``template_key``, envelope drift,
                malformed JSON, or default_config that fails
                ``policy.engine.validate_spec_for_template`` for the resolved key.
            TemplateAlreadyExistsError: ``template_key`` collision.
            sqlalchemy.exc.IntegrityError: any other DB integrity failure
                (e.g., bad ``benchmark_subject_agent_id`` FK). Propagated
                as-is so callers can classify accurately; only duplicate
                ``template_key`` is rewritten to a domain error.
        """
        _validate_allowed_fields_for_template(template_key, allowed_fields_json)
        self._validate_default_config(template_key, default_config_json)

        # Explicit pre-check so we classify duplicate-key errors without
        # guessing at IntegrityError semantics (which vary across SQLite /
        # Postgres / FK / unique constraints). A race with a concurrent
        # inserter is still possible; in that case the DB unique index
        # guarantees correctness and we let IntegrityError propagate rather
        # than masking it as a duplicate-key error when it may be something
        # else.
        existing = await self.get_template_by_key(template_key)
        if existing is not None:
            raise TemplateAlreadyExistsError(
                f"template_key {template_key!r} already exists"
            )

        template = AgentTemplate(
            template_key=template_key,
            template_version=template_version,
            description=description,
            allowed_fields_json=allowed_fields_json,
            default_config_json=default_config_json,
            system_prompt=system_prompt,
            is_deployable=1 if is_deployable else 0,
            benchmark_subject_agent_id=benchmark_subject_agent_id,
        )
        self.db.add(template)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            # Reconciliation: the pre-check above handles the single-writer
            # duplicate case, but concurrent writers can both pass that check
            # and race to the DB unique index. Re-read after rollback: if the
            # row now exists, this failure is a duplicate-key collision and
            # becomes TemplateAlreadyExistsError. Otherwise the failure was
            # something else (bad FK, CHECK, future constraints) and must
            # surface truthfully as IntegrityError.
            await self.db.rollback()
            existing = await self.get_template_by_key(template_key)
            if existing is not None:
                raise TemplateAlreadyExistsError(
                    f"template_key {template_key!r} already exists"
                ) from exc
            raise
        return template

    @staticmethod
    def _validate_allowed_fields(allowed_fields_json: str) -> None:
        """Legacy back-compat shim — delegates to the swap envelope.

        Kept so any caller that has not migrated to
        ``_validate_allowed_fields_for_template`` still works for swap
        registrations.  All NEW callers MUST pass ``template_key`` explicitly.
        """
        _validate_allowed_fields_for_template("swap_executor_v1", allowed_fields_json)

    def _validate_default_config(self, template_key: str, default_config_json: str) -> None:
        """Parse ``default_config_json`` and enforce template-aware policy validation.

        The decoded value must be a JSON object and must satisfy
        ``validate_spec_for_template`` for the given ``template_key``.
        """
        try:
            decoded = json.loads(default_config_json)
        except json.JSONDecodeError as exc:
            raise TemplateValidationError(
                f"default_config_json is not valid JSON: {exc.msg}"
            ) from exc
        if not isinstance(decoded, dict):
            raise TemplateValidationError(
                "default_config_json must decode to a JSON object"
            )
        result = validate_spec_for_template(template_key, decoded)
        if not result.ok:
            raise TemplateValidationError(
                "default_config failed policy validation: "
                + "; ".join(result.errors)
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get_template_by_key(self, key: str) -> Optional[AgentTemplate]:
        """Return the template for ``key`` or ``None`` if missing."""
        result = await self.db.execute(
            select(AgentTemplate).where(AgentTemplate.template_key == key)
        )
        return result.scalar_one_or_none()

    async def list_templates(
        self, deployable_only: bool = False
    ) -> list[AgentTemplate]:
        """List templates for catalog display, newest first.

        Ordered by ``created_at`` descending per the Task 3 contract, with
        ``template_id`` descending as a stable tie-breaker when two rows
        land at the same ``server_default=func.now()`` tick.
        """
        stmt = select(AgentTemplate).order_by(
            AgentTemplate.created_at.desc(),
            AgentTemplate.template_id.desc(),
        )
        if deployable_only:
            # is_deployable is stored as Integer (0/1) for SQLite/Postgres
            # portability; compare numerically rather than with Python truthiness.
            stmt = stmt.where(AgentTemplate.is_deployable == 1)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_template_with_flagship_info(
        self, key: str
    ) -> Optional[dict[str, Any]]:
        """Return template metadata plus the linked flagship trust label.

        ``flagship_trust_label`` is ``None`` until Task 18/D-1 deploys a live
        flagship ``AgentInstance`` for this template. It is sourced from
        ``agent_instances.trust_label`` (the instance-layer marker), never
        from ``agents`` (the agent layer carries ``subject_type`` only).
        """
        template = await self.get_template_by_key(key)
        if template is None:
            return None

        response: dict[str, Any] = {
            "template_id": template.template_id,
            "template_key": template.template_key,
            "template_version": template.template_version,
            "description": template.description,
            "system_prompt": template.system_prompt,
            "allowed_fields": json.loads(template.allowed_fields_json),
            "default_config": json.loads(template.default_config_json),
            "is_deployable": bool(template.is_deployable),
            "benchmark_subject_agent_id": template.benchmark_subject_agent_id,
            "flagship_trust_label": None,
        }

        # Singleton-flagship lookup: only a LIVE instance with the
        # canonical-template trust label counts. Customized instances linked
        # to the same template must NOT surface as flagship.
        if template.benchmark_subject_agent_id is not None:
            result = await self.db.execute(
                select(AgentInstance.trust_label)
                .where(
                    AgentInstance.template_id == template.template_id,
                    AgentInstance.trust_label == _FLAGSHIP_TRUST_LABEL,
                    AgentInstance.status == "live",
                )
                .limit(1)
            )
            label = result.scalar_one_or_none()
            if label is not None:
                response["flagship_trust_label"] = label

        return response
