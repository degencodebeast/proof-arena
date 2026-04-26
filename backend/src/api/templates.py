"""Task 4 — public template catalog API.

Two public read-only endpoints over the shipped Task 3
`TemplateService`:

- `GET /api/v1/templates` — catalog list (deployable + signpost),
  newest first. Narrow summary shape (5 keys per row) suitable for a
  grid UI.
- `GET /api/v1/templates/{template_key}` — detail view with parsed
  `allowed_fields` + `default_config` and live-flagship lineage via
  `TemplateService.get_template_with_flagship_info`.

No auth (public reads). No write endpoints. No benchmark scores —
template-layer responses only surface lineage via the flagship trust
label. See `.taskmaster/docs/task4-edge-case-spec.md`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db

# NOTE: `TemplateService` is imported lazily inside each route handler,
# NOT at module load. Why: `test_phase_p0_interfaces::test_importing_policy_engine_is_side_effect_free`
# pops `src.policy.engine` from `sys.modules` and re-imports it to
# verify side-effect-free loading. If `src.services.template_service`
# is imported at router-load time (via `src.main.app`), its
# module-level `InstancePolicyEngine` reference is bound to the
# PRE-reload class object; a later `isinstance(...)` against the
# POST-reload class fails because they are distinct Python objects.
# Deferring the import until request time keeps the service's class
# binding consistent with the current `sys.modules` state.
router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("")
async def list_templates(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Public catalog of all templates (deployable + signpost)."""
    from src.services.template_service import TemplateService

    service = TemplateService(db)
    templates = await service.list_templates()
    return [
        {
            "template_key": t.template_key,
            "template_version": t.template_version,
            "description": t.description,
            "is_deployable": bool(t.is_deployable),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in templates
    ]


@router.get("/{template_key}")
async def get_template_detail(
    template_key: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Public template detail including flagship lineage info."""
    from src.services.template_service import TemplateService

    service = TemplateService(db)
    response = await service.get_template_with_flagship_info(template_key)
    if response is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return response
