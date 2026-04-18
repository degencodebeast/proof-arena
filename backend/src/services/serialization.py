"""Shared canonical JSON serialization for event payloads and hashing.

Used by RunnerService, RunAuditor, and SettlementVerifier.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


class EventJSONEncoder(json.JSONEncoder):
    """Deterministic JSON encoder for event payloads."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("ascii")
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        return super().default(obj)


def serialize_payload(payload: Any) -> str:
    """Serialize a payload to canonical JSON for storage and hashing."""
    return json.dumps(payload, cls=EventJSONEncoder, sort_keys=True, separators=(",", ":"))


def compute_run_log_hash(events: list[dict[str, Any]]) -> str:
    """Compute SHA-256 of events in deterministic order.

    Events sorted by sequence_no. Each serialized with sorted keys, no whitespace.
    """
    sorted_events = sorted(events, key=lambda e: e.get("sequence_no", 0))
    hasher = hashlib.sha256()
    for event in sorted_events:
        event_bytes = json.dumps(
            event, cls=EventJSONEncoder, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        hasher.update(event_bytes)
    return hasher.hexdigest()
