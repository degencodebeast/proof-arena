"""V2 trust-label contract — single source of truth for trust_label values.

Three values locked for V2 (see ``V2_DESIGN_SPEC.md §10`` and plan
``§3 Trust-label contract``):

- ``BENCHMARKED_CANONICAL_TEMPLATE`` — carried on the flagship
  ``agent_instances`` row deployed in Task 18 / D-1. The flagship ``agents``
  row carries ``subject_type = canonical_template`` and does NOT have a
  ``trust_label`` field.
- ``BENCHMARK_COMPATIBLE_CUSTOMIZED_INSTANCE`` — assigned to every
  user-deployed hosted instance when the deploy saga transitions to
  ``live``. Default value on the ``agent_instances.trust_label`` column.
- ``EXTERNAL_CUSTOM_RUNTIME`` — **reserved** in the V2 contract. No V2
  code path assigns it; the enum member exists so the schema, API
  responses, and the frontend recognise the value without a retrofit when
  (post-V2) an external-runtime path ships.

The DB-level CHECK constraint on ``agent_instances.trust_label`` rejects
any off-contract value. Because ``db.models`` cannot import from the
``src.integrity`` package (circular via its eager ``__init__``), the CHECK
list is duplicated as a tuple in ``db.models`` and held in sync with this
enum by a drift-guard test.
"""

from __future__ import annotations

from enum import Enum


class TrustLabel(str, Enum):
    """The three V2 trust-label values. See module docstring for semantics."""

    BENCHMARKED_CANONICAL_TEMPLATE = "benchmarked_canonical_template"
    BENCHMARK_COMPATIBLE_CUSTOMIZED_INSTANCE = (
        "benchmark_compatible_customized_instance"
    )
    EXTERNAL_CUSTOM_RUNTIME = "external_custom_runtime"


def trust_label_values() -> tuple[str, ...]:
    """Return the full set of valid ``agent_instances.trust_label`` strings.

    Consumed by callers building CHECK SQL or API responses — keeps them
    from hardcoding the vocabulary in multiple places.
    """

    return tuple(m.value for m in TrustLabel)
