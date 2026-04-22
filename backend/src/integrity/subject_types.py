"""V2 subject-type contract — single source of truth for subject_type values.

Two values locked for V2 (see ``V2_DESIGN_SPEC.md §3`` and plan §10):

- ``CANONICAL_TEMPLATE`` — flagship / canonical subject. Carried on the
  flagship ``agents`` row and on ``rank_snapshots`` tied to canonical
  subjects. All V1-origin rows are backfilled to this value on migration.
- ``CUSTOMIZED_INSTANCE`` — user-deployed derivative subject. Written by
  the V2 hosted deploy path / benchmark attachment code (Task 13 / C1).

The ``subject_type`` axis partitions reputation. Leaderboard read models
(Task 16) filter on it so canonical-template and customized-instance
histories never blend. This is distinct from ``trust_label`` (instance
layer, on ``agent_instances``) — DO NOT confuse the two axes.

The DB-level CHECK constraint on ``agents.subject_type`` and
``rank_snapshots.subject_type`` rejects any off-contract value. Because
``db.models`` cannot import from the ``src.integrity`` package (circular
via its eager ``__init__``), the CHECK list is duplicated as a tuple in
``db.models`` and held in sync with this enum by a drift-guard test.
"""

from __future__ import annotations

from enum import Enum


class SubjectType(str, Enum):
    """The two V2 subject-type values. See module docstring for semantics."""

    CANONICAL_TEMPLATE = "canonical_template"
    CUSTOMIZED_INSTANCE = "customized_instance"


def subject_type_values() -> tuple[str, ...]:
    """Return the full set of valid ``subject_type`` strings.

    Consumed by callers building CHECK SQL or API responses — keeps them
    from hardcoding the vocabulary in multiple places.
    """

    return tuple(m.value for m in SubjectType)
