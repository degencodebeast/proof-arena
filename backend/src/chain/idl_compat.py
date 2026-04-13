"""IDL compatibility layer — converts Anchor 0.32.1 IDL (spec 0.1.0)
to the legacy format that anchorpy 0.21.0 can parse.

Anchor 0.32.1 generates a new IDL spec with:
- "pubkey" instead of "publicKey"
- {"defined": {"name": "Foo"}} instead of {"defined": "Foo"}
- "writable"/"signer" instead of "isMut"/"isSigner"

This module converts between formats so anchorpy can load the Program.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def convert_type(t: Any) -> Any:
    """Convert a new-spec IDL type to legacy format."""
    if isinstance(t, str):
        return "publicKey" if t == "pubkey" else t
    if isinstance(t, dict):
        if "defined" in t:
            d = t["defined"]
            return {"defined": d["name"]} if isinstance(d, dict) else {"defined": d}
        if "option" in t:
            return {"option": convert_type(t["option"])}
        if "vec" in t:
            return {"vec": convert_type(t["vec"])}
        if "array" in t:
            return {"array": [convert_type(t["array"][0]), t["array"][1]]}
    return t


def convert_idl(new_idl: dict) -> dict:
    """Convert Anchor 0.32.1 IDL to legacy format for anchorpy."""
    legacy: dict[str, Any] = {
        "version": new_idl["metadata"]["version"],
        "name": new_idl["metadata"]["name"],
        "instructions": [],
        "accounts": [],
        "types": [],
        "events": [],
        "errors": [],
    }

    for acc_def in new_idl.get("accounts", []):
        legacy["accounts"].append({
            "name": acc_def["name"],
            "type": {"kind": "struct", "fields": []},
        })

    for type_def in new_idl.get("types", []):
        t = type_def["type"]
        if t["kind"] == "enum":
            legacy["types"].append({
                "name": type_def["name"],
                "type": {
                    "kind": "enum",
                    "variants": [{"name": v["name"]} for v in t["variants"]],
                },
            })
        elif t["kind"] == "struct":
            legacy["types"].append({
                "name": type_def["name"],
                "type": {
                    "kind": "struct",
                    "fields": [
                        {"name": f["name"], "type": convert_type(f["type"])}
                        for f in t.get("fields", [])
                    ],
                },
            })

    for ix in new_idl["instructions"]:
        legacy["instructions"].append({
            "name": ix["name"],
            "accounts": [
                {
                    "name": a["name"],
                    "isMut": a.get("writable", False),
                    "isSigner": a.get("signer", False),
                }
                for a in ix["accounts"]
            ],
            "args": [
                {"name": a["name"], "type": convert_type(a["type"])}
                for a in ix.get("args", [])
            ],
        })

    for ev in new_idl.get("events", []):
        legacy["events"].append({
            "name": ev["name"],
            "fields": [
                {"name": f["name"], "type": convert_type(f["type"]), "index": False}
                for f in ev.get("fields", [])
            ],
        })

    for err in new_idl.get("errors", []):
        legacy["errors"].append({
            "code": err["code"],
            "name": err["name"],
            "msg": err.get("msg", ""),
        })

    return legacy


def load_and_convert(idl_path: str | Path) -> str:
    """Load a new-spec IDL file and return legacy JSON string."""
    with open(idl_path) as f:
        new_idl = json.load(f)
    legacy = convert_idl(new_idl)
    return json.dumps(legacy)
