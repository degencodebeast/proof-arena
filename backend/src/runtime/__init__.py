"""V2 hosted-instance runtime package.

Exports the provider-agnostic ``InstanceRuntime`` protocol plus — when
available — the concrete ``AgentOSRuntime`` implementation. The import
of ``AgentOSRuntime`` is guarded so V1-only paths (e.g. ``LocalAgentProvider``)
keep importing cleanly on environments without the ``agno.client`` SDK.
The AgentOS SDK import itself is confined to ``src/runtime/agentos.py``
per V2 plan invariant 4.

Import-guard discipline: we probe the SDK module with ``find_spec``
before importing the wrapper, then import the wrapper UNGUARDED so any
real bug inside ``src.runtime.agentos`` (typos, broken transitive
imports, etc.) propagates loudly instead of being silently demoted to
the ``AgentOSRuntime = None`` sentinel path.
"""

from __future__ import annotations

import importlib.util

from src.runtime.base import InstanceHandle, InstanceRuntime, InstanceSpec

if importlib.util.find_spec("agno.client") is None:
    AgentOSRuntime = None  # type: ignore[assignment]
    AgentOSRuntimeError = None  # type: ignore[assignment]
    _AGENTOS_RUNTIME_AVAILABLE = False
else:
    # SDK is installed — any ImportError from here on is a real wrapper bug.
    # Do NOT wrap in try/except ImportError.
    from src.runtime.agentos import AgentOSRuntime, AgentOSRuntimeError
    _AGENTOS_RUNTIME_AVAILABLE = True


__all__ = [
    "AgentOSRuntime",
    "AgentOSRuntimeError",
    "InstanceHandle",
    "InstanceRuntime",
    "InstanceSpec",
]
