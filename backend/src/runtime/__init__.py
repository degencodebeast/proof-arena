"""V2 hosted-instance runtime package.

Exports the provider-agnostic `InstanceRuntime` protocol only. Concrete
runtime implementations (e.g. AgentOS-backed) live in separate modules
and are loaded by services, not by the protocol module.
"""

from src.runtime.base import InstanceHandle, InstanceRuntime, InstanceSpec

__all__ = ["InstanceHandle", "InstanceRuntime", "InstanceSpec"]
