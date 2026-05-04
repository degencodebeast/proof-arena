"""ChallengeAdapter protocol gains 4 hooks (spec §5.4)."""
from __future__ import annotations

from src.challenges.base import ChallengeAdapter


def test_protocol_declares_allowed_action_types():
    assert hasattr(ChallengeAdapter, "allowed_action_types")


def test_protocol_declares_should_flatten():
    assert hasattr(ChallengeAdapter, "should_flatten")


def test_protocol_declares_compute_ending_value():
    assert hasattr(ChallengeAdapter, "compute_ending_value")


def test_protocol_declares_emit_run_evidence():
    assert hasattr(ChallengeAdapter, "emit_run_evidence")
