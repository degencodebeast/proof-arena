"""v2_a5_trust_label_check

Revision ID: c1e9a45b7d3f
Revises: b5d2c8f91a7e
Create Date: 2026-04-20

V2 Task A-5 — add CHECK constraint on ``agent_instances.trust_label`` so
every recorded value is one of the locked V2 trust-label enum values
(``benchmarked_canonical_template``, ``benchmark_compatible_customized_instance``,
``external_custom_runtime``). See ``src/integrity/trust_labels.py``.

Backfill: any pre-existing ``trust_label`` value outside the contract is
coerced to the default ``benchmark_compatible_customized_instance`` before
the constraint applies. In practice existing rows all already carry the
default, so the UPDATE is a defensive no-op at the time of writing.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c1e9a45b7d3f"
down_revision: Union[str, Sequence[str], None] = "b5d2c8f91a7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept in sync with ``TrustLabel`` enum by
# ``tests/test_task_a5_trust_label.py::test_models_trust_label_tuple_matches_enum``.
_ALLOWED = (
    "benchmarked_canonical_template",
    "benchmark_compatible_customized_instance",
    "external_custom_runtime",
)


def _in_list_sql() -> str:
    return ", ".join(f"'{v}'" for v in _ALLOWED)


def upgrade() -> None:
    # Backfill any off-contract values to the column default.
    op.execute(
        "UPDATE agent_instances "
        "SET trust_label = 'benchmark_compatible_customized_instance' "
        f"WHERE trust_label NOT IN ({_in_list_sql()})"
    )
    op.create_check_constraint(
        "ck_agent_instances_trust_label",
        "agent_instances",
        f"trust_label IN ({_in_list_sql()})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_agent_instances_trust_label", "agent_instances", type_="check"
    )
