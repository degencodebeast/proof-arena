"""v2_task25_rebalance_signpost

Revision ID: c3e7d6b9f4a2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-23

V2 Task 25 — register ``rebalance_executor_v1`` as a non-deployable
signpost template.

Scope (locked in `.taskmaster/docs/task25-edge-case-spec.md`):
- Signpost ONLY. No real rebalance runtime, no AgentOS agent, no
  tool-calling harness, no benchmark path.
- Inserts a single ``agent_templates`` row with empty envelope /
  empty default_config / empty system_prompt / ``is_deployable=0`` /
  ``benchmark_subject_agent_id=NULL``.
- Bypasses ``TemplateService.register_template()`` deliberately:
  that service enforces set-equality with the V2 5-field envelope
  and would reject ``allowed_fields_json="[]"``. The migration is the
  only valid registration channel for this row.

Reversible via ``DELETE … WHERE template_key='rebalance_executor_v1'``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e7d6b9f4a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SIGNPOST_KEY = "rebalance_executor_v1"
_SIGNPOST_VERSION = "rebalance_executor_v1"
_SIGNPOST_DESCRIPTION = (
    "Autonomous portfolio rebalancing agent. "
    "Maintains target allocations by executing trades to restore balance. "
    "Not yet live - follow-on family planned for post-V2."
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO agent_templates (
                template_key,
                template_version,
                description,
                allowed_fields_json,
                default_config_json,
                system_prompt,
                is_deployable,
                benchmark_subject_agent_id
            ) VALUES (
                :template_key,
                :template_version,
                :description,
                '[]',
                '{}',
                '',
                0,
                NULL
            )
            """
        ).bindparams(
            template_key=_SIGNPOST_KEY,
            template_version=_SIGNPOST_VERSION,
            description=_SIGNPOST_DESCRIPTION,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM agent_templates WHERE template_key = :template_key"
        ).bindparams(template_key=_SIGNPOST_KEY)
    )
