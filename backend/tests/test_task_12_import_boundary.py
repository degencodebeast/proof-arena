"""Task 12 subtask 12.3 — runtime import-boundary enforcement.

V2 plan invariant 4 ("runtime import boundary"): the **AgentOS SDK**
(``agno.client`` — the hosted-runtime RPC client) may be imported in
exactly ONE V2 module — ``backend/src/runtime/agentos.py``. Every other
``backend/src/**`` file must depend only on the provider-agnostic
``InstanceRuntime`` protocol in ``src.runtime.base``.

The broader ``agno`` package is **not** banned: V1 uses ``agno.agent``,
``agno.tools``, and ``agno.models.*`` as in-process framework primitives
in ``LocalAgentProvider`` and the V1 tool definitions. Those are
framework-level imports, not AgentOS-SDK calls to a remote server.

AST-walk based (not regex) so comments, docstrings, and string literals
that mention "agno" don't produce false positives.

Also verifies the ``src.runtime`` package imports cleanly even when the
``agno`` SDK is not installed (Task 12.3 invariant IB3 / N15).
"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t12-3")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


_BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
_ALLOWED_FILE = _BACKEND_SRC / "runtime" / "agentos.py"


def _python_files() -> list[Path]:
    return [p for p in _BACKEND_SRC.rglob("*.py") if "__pycache__" not in p.parts]


def _imports_agentos_sdk(path: Path) -> list[str]:
    """Return offending ``agno.client`` imports, if any.

    Scope: ``agno.client`` and submodules only — this is the AgentOS
    hosted-runtime RPC client. The broader ``agno`` framework
    (``agno.agent``, ``agno.tools``, ``agno.models.*``) is NOT banned;
    V1 uses it in ``LocalAgentProvider`` and tool definitions.
    """
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:  # pragma: no cover — shouldn't happen in a healthy tree
        pytest.fail(f"{path}: SyntaxError in source: {e}")

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "agno.client" or alias.name.startswith("agno.client."):
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "agno.client" or mod.startswith("agno.client."):
                for alias in node.names:
                    offenders.append(f"from {mod} import {alias.name}")
    return offenders


# ----------------------------------------------------------------------
# Invariant IB1/IB2 — only agentos.py imports agno
# ----------------------------------------------------------------------


def test_only_agentos_py_imports_agentos_sdk():
    """Enforce the V2 plan invariant 4 runtime-import boundary."""
    assert _ALLOWED_FILE.is_file(), (
        f"Task 12's single AgentOS import boundary is missing: {_ALLOWED_FILE}"
    )

    offenders: dict[Path, list[str]] = {}
    for path in _python_files():
        if path == _ALLOWED_FILE:
            continue
        hits = _imports_agentos_sdk(path)
        if hits:
            offenders[path] = hits

    if offenders:
        msg_lines = [
            f"V2 invariant 4 violated — agno imports found outside "
            f"{_ALLOWED_FILE.relative_to(_BACKEND_SRC.parent)}:"
        ]
        for p, hits in offenders.items():
            rel = p.relative_to(_BACKEND_SRC.parent)
            for h in hits:
                msg_lines.append(f"  {rel}: {h}")
        pytest.fail("\n".join(msg_lines))


def test_agentos_py_does_import_agno():
    """Sanity — the allowed file must actually contain an agno import.

    Guards against someone "fixing" the boundary test by deleting the
    import from the wrapper. The SDK is a genuine runtime dependency
    of the wrapper; without it there's no wrapper.
    """
    hits = _imports_agentos_sdk(_ALLOWED_FILE)
    assert hits, f"{_ALLOWED_FILE} must import from agno; the wrapper depends on it."


# ----------------------------------------------------------------------
# Invariant IB3/N15 — runtime package imports without agno
# ----------------------------------------------------------------------


def test_runtime_package_imports_without_agno():
    """``src.runtime`` must import cleanly even when agno is absent.

    We can't uninstall agno in-process, but we CAN ensure the package's
    ``__init__.py`` uses a guarded import. A subprocess that deletes
    ``agno`` from sys.modules and blocks re-import proves the pattern.
    """
    script = (
        "import sys\n"
        "# Simulate 'agno not installed' via the stdlib-documented sentinel:\n"
        "# sys.modules[name] = None causes find_spec(name) to return None AND\n"
        "# any `import name` to raise ModuleNotFoundError.\n"
        "for m in list(sys.modules):\n"
        "    if m == 'agno' or m.startswith('agno.'):\n"
        "        del sys.modules[m]\n"
        "sys.modules['agno'] = None\n"
        "sys.modules['agno.client'] = None\n"
        "# Flush any src.runtime cached with the real agno import.\n"
        "for m in list(sys.modules):\n"
        "    if m == 'src.runtime' or m.startswith('src.runtime.'):\n"
        "        del sys.modules[m]\n"
        "# Importing src.runtime must now succeed.\n"
        "import src.runtime as rt\n"
        "assert rt.InstanceRuntime is not None\n"
        "assert rt.InstanceHandle is not None\n"
        "assert rt.InstanceSpec is not None\n"
        "# AgentOSRuntime should be a None sentinel when agno is unavailable.\n"
        "assert rt.AgentOSRuntime is None, (\n"
        "    f'expected AgentOSRuntime=None when agno is blocked, got {rt.AgentOSRuntime!r}'\n"
        ")\n"
        "assert rt.AgentOSRuntimeError is None\n"
        "print('OK')\n"
    )
    # Run in a subprocess so the meta_path blocker doesn't poison other tests.
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(_BACKEND_SRC.parent),
        env={**os.environ, "PYTHONPATH": str(_BACKEND_SRC.parent)},
    )
    assert result.returncode == 0, (
        f"Runtime package failed to import without agno.\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "OK" in result.stdout


def test_runtime_package_exports_agentos_runtime_when_agno_installed():
    """With agno installed (our venv has it), AgentOSRuntime must be the real class."""
    pytest.importorskip(
        "agno.client",
        reason="agno SDK not installed; this test is a no-op.",
    )
    # Force a fresh import so prior test state doesn't interfere.
    for mod in list(sys.modules):
        if mod == "src.runtime" or mod.startswith("src.runtime."):
            del sys.modules[mod]

    rt = importlib.import_module("src.runtime")
    assert rt.AgentOSRuntime is not None
    assert rt.AgentOSRuntimeError is not None
    # Must be a class, not a sentinel.
    assert isinstance(rt.AgentOSRuntime, type)
    assert isinstance(rt.AgentOSRuntimeError, type)


def test_runtime_init_does_not_swallow_real_wrapper_bugs(tmp_path):
    """If ``src.runtime.agentos`` fails to import for a reason OTHER than
    the AgentOS SDK being missing (e.g. a typo, a missing helper import),
    that failure MUST propagate. Silently demoting real bugs to the
    ``AgentOSRuntime = None`` sentinel masks ship-breaking regressions.
    """
    # Build a tiny sandbox backend tree with a broken src/runtime/agentos.py.
    # We point a subprocess at it, keep the real backend's agno dep reachable,
    # and verify the subprocess exits non-zero with the synthetic import error.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "runtime").mkdir()
    (tmp_path / "src" / "runtime" / "base.py").write_text(
        "from dataclasses import dataclass, field\n"
        "from typing import Any, Protocol, runtime_checkable\n"
        "@dataclass(frozen=True)\n"
        "class InstanceSpec:\n"
        "    template_key: str\n"
        "    template_version: str\n"
        "    effective_config: dict\n"
        "    instance_owner_ref: str\n"
        "@dataclass\n"
        "class InstanceHandle:\n"
        "    instance_id: str\n"
        "    extra: dict = field(default_factory=dict)\n"
        "@runtime_checkable\n"
        "class InstanceRuntime(Protocol):\n"
        "    async def deploy(self, spec): ...\n"
        "    async def invoke_decide(self, handle, state): ...\n"
        "    async def teardown(self, handle): ...\n",
        encoding="utf-8",
    )
    # Broken agentos.py: agno is available, but a sibling import is wrong.
    (tmp_path / "src" / "runtime" / "agentos.py").write_text(
        "from agno.client import AgentOSClient  # SDK is fine\n"
        "from src.runtime.base import InstanceHandle  # fine\n"
        "# Real bug: this module does not exist.\n"
        "from src.runtime._definitely_not_a_real_module import helper  # noqa: F401\n"
        "class AgentOSRuntime: ...\n"
        "class AgentOSRuntimeError(Exception): ...\n",
        encoding="utf-8",
    )
    # Reuse the real __init__.py under test.
    real_init = (
        _BACKEND_SRC / "runtime" / "__init__.py"
    ).read_text(encoding="utf-8")
    (tmp_path / "src" / "runtime" / "__init__.py").write_text(
        real_init, encoding="utf-8"
    )

    script = (
        "import sys\n"
        "import importlib\n"
        "sys.path.insert(0, %r)\n"
        "# Flush any cached src.runtime entries pointing at the real backend.\n"
        "for m in list(sys.modules):\n"
        "    if m == 'src' or m.startswith('src.'):\n"
        "        del sys.modules[m]\n"
        "try:\n"
        "    importlib.import_module('src.runtime')\n"
        "except ModuleNotFoundError as e:\n"
        "    msg = str(e)\n"
        "    assert '_definitely_not_a_real_module' in msg, msg\n"
        "    print('PROPAGATED')\n"
        "    sys.exit(0)\n"
        "print('SWALLOWED')\n"
        "sys.exit(1)\n"
    ) % str(tmp_path)

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    assert result.returncode == 0, (
        f"Real wrapper bug was swallowed by the conditional export.\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "PROPAGATED" in result.stdout
