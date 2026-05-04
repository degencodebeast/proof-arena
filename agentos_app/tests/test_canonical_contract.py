"""Task 29 — RED tests for the agentos_app canonical-template contract.

Covers ``.taskmaster/docs/task29-edge-case-spec.md`` §11 T1-T9. Tests
run against the in-tree backend via PYTHONPATH (set by the
``canonical_template_contract`` module's own ``sys.path`` insertion).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path


# Ensure the agentos_app package + sibling backend are importable when
# this file is run from arbitrary cwd (e.g. agent-rank/backend pytest).
_AGENT_RANK = Path(__file__).resolve().parents[2]
for p in (_AGENT_RANK / "backend", _AGENT_RANK):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

# Sandbox env so `BaseSettings` does not pick up the operator's local
# .env at import time.
os.environ.setdefault("OPENROUTER_API_KEY", "")


# ---------------------------------------------------------------------
# T1 — config defaults
# ---------------------------------------------------------------------


def test_config_defaults():
    from agentos_app.config import AgentOSAppSettings

    s = AgentOSAppSettings(_env_file=None)  # type: ignore[call-arg]
    assert s.canonical_agent_id == "swap_executor_v1"
    assert s.host == "0.0.0.0"
    assert s.port == 7000
    assert s.database_url == ""
    assert s.llm_provider == "openrouter"
    assert s.llm_model == "openai/gpt-4o-mini"


# ---------------------------------------------------------------------
# T2 — single source of truth (object identity, not just equality)
# ---------------------------------------------------------------------


def test_seed_is_single_source_of_truth():
    from agentos_app.canonical_template_contract import (
        SWAP_EXECUTOR_V1_SEED as agentos_seed,
    )
    from src.services.template_service import (
        SWAP_EXECUTOR_V1_SEED as backend_seed,
    )

    # Same Python object — guarantees a backend-side edit is picked up
    # at next AgentOS process restart, with no fork.
    assert agentos_seed is backend_seed


# ---------------------------------------------------------------------
# T3 — agent factory matches the contract
# ---------------------------------------------------------------------


def test_agent_factory_matches_contract():
    from agentos_app.agent import build_canonical_swap_executor_agent
    from agentos_app.canonical_template_contract import (
        SWAP_EXECUTOR_V1_SEED,
    )
    from agentos_app.config import AgentOSAppSettings

    settings = AgentOSAppSettings(_env_file=None)  # type: ignore[call-arg]
    agent = build_canonical_swap_executor_agent(settings)

    assert agent.id == settings.canonical_agent_id == "swap_executor_v1"
    # `instructions` may be a str or a list; for V2 we set a str.
    assert agent.instructions == SWAP_EXECUTOR_V1_SEED["system_prompt"]


# ---------------------------------------------------------------------
# T4 — agent has no tools (decision-only)
# ---------------------------------------------------------------------


def test_agent_is_decision_only():
    from agentos_app.agent import build_canonical_swap_executor_agent
    from agentos_app.config import AgentOSAppSettings

    settings = AgentOSAppSettings(_env_file=None)  # type: ignore[call-arg]
    agent = build_canonical_swap_executor_agent(settings)

    # Agno may store tools as None, [], or []. Treat None and [] both
    # as "no tools attached".
    tools = agent.tools or []
    assert len(tools) == 0, (
        "V2 contract: AgentOS canonical agent is decision-only; "
        f"got tools={tools!r}"
    )


# ---------------------------------------------------------------------
# T5 — app factory declares the canonical agent
# ---------------------------------------------------------------------


def test_app_factory_declares_canonical_agent():
    from fastapi import FastAPI

    from agentos_app.app import build_agentos, build_agentos_app
    from agentos_app.config import AgentOSAppSettings

    settings = AgentOSAppSettings(_env_file=None)  # type: ignore[call-arg]
    os_instance = build_agentos(settings)
    ids = sorted(a.id for a in os_instance.agents)
    assert ids == ["rebalance_executor_v1", "swap_executor_v1"], (
        f"Phase B / Task 6 contract: AgentOS app must register both canonical "
        f"agents; got {ids!r}"
    )
    assert all(a.tools == [] for a in os_instance.agents), (
        f"Decision-only invariant: tools=[] on both canonical agents"
    )

    app = build_agentos_app(settings)
    assert isinstance(app, FastAPI)


# ---------------------------------------------------------------------
# T6 — no `agno.client` import in agentos_app (server side only).
# Verified via AST walk so docstring/string mentions of "agno.client"
# don't false-positive.
# ---------------------------------------------------------------------


_AGENTOS_APP_DIR = _AGENT_RANK / "agentos_app"


_SKIP_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".pytest_cache",
        "site-packages",
        ".git",
    }
)


def _python_files(root: Path) -> list[Path]:
    """Iterate the package's first-party Python files only.

    Skips virtualenvs / site-packages / caches so the import-boundary
    checks below scan only Proof Arena code.
    """
    return [
        p
        for p in root.rglob("*.py")
        if not (set(p.parts) & _SKIP_DIR_NAMES)
    ]


def _imports_matching(path: Path, target_prefix: str) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == target_prefix or alias.name.startswith(
                    target_prefix + "."
                ):
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == target_prefix or mod.startswith(target_prefix + "."):
                for alias in node.names:
                    hits.append(f"from {mod} import {alias.name}")
    return hits


def test_no_agentos_sdk_client_import():
    """`agno.client` is RESERVED for backend's runtime/agentos.py.

    The agentos_app is the SERVER side; it must not import the client
    SDK. Smoke script is allowed to import inside its function body
    because operator boundary is explicit there — but we still expect
    ZERO module-top-level `agno.client` imports anywhere in the
    package. The smoke script's import is INSIDE a function so the
    AST walk should still surface it.

    Resolution: the smoke script imports `from agno.client import
    AgentOSClient` lazily inside `_run_async`. That is intentional —
    operator-boundary code, not product runtime. The check below
    counts module-level imports only.
    """
    # Use the package-level walk helper that skips .venv / site-packages
    # / caches so the boundary scan covers only Proof Arena code.
    offenders: dict[Path, list[str]] = {}
    for f in _python_files(_AGENTOS_APP_DIR):
        # Only flag MODULE-LEVEL imports of agno.client. Function-local
        # imports are fine for the operator-boundary smoke script.
        src = f.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(f))
        for node in tree.body:  # module-level only
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "agno.client" or alias.name.startswith(
                        "agno.client."
                    ):
                        offenders.setdefault(f, []).append(
                            f"import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == "agno.client" or mod.startswith("agno.client."):
                    for alias in node.names:
                        offenders.setdefault(f, []).append(
                            f"from {mod} import {alias.name}"
                        )
    assert not offenders, (
        "agentos_app must not import agno.client at module level "
        "(server side); offenders:\n  " + "\n  ".join(
            f"{p}: {hits}" for p, hits in offenders.items()
        )
    )


# ---------------------------------------------------------------------
# T7 — no wallet/Orca/swap-execution dependency in agentos_app.
# ---------------------------------------------------------------------


def test_decision_only_dependency_boundary():
    """The agent is decision-only; it must not reach into wallet/Orca/Privy."""
    forbidden_prefixes = (
        "solders",
        "src.services.wallet_service",
        "src.services.swap_service",
        "src.services.privy_signing",
    )
    offenders: dict[Path, list[str]] = {}
    for f in _python_files(_AGENTOS_APP_DIR):
        for prefix in forbidden_prefixes:
            hits = _imports_matching(f, prefix)
            if hits:
                offenders.setdefault(f, []).extend(hits)
    assert not offenders, (
        "agentos_app must stay decision-only — no wallet/Orca/Privy "
        "imports. Offenders:\n  " + "\n  ".join(
            f"{p}: {hits}" for p, hits in offenders.items()
        )
    )


# ---------------------------------------------------------------------
# T8 — env-pair contract documented in README + v2_infra.md.
# ---------------------------------------------------------------------


def test_env_pair_documented():
    readme = (_AGENTOS_APP_DIR / "README.md").read_text(encoding="utf-8")
    assert "AGENTOS_CANONICAL_AGENT_ID" in readme
    assert "swap_executor_v1" in readme

    infra = (_AGENT_RANK / "scripts" / "v2_infra.md").read_text(
        encoding="utf-8"
    )
    assert "AGENTOS_API_URL" in infra
    assert "AGENTOS_CANONICAL_AGENT_ID" in infra
    assert "swap_executor_v1" in infra


# ---------------------------------------------------------------------
# T9 — smoke script CLI surface.
# ---------------------------------------------------------------------


def test_smoke_script_help():
    """`python -m agentos_app.scripts.smoke --help` exits 0."""
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{_AGENT_RANK}{os.pathsep}{_AGENT_RANK / 'backend'}"
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    result = subprocess.run(
        [sys.executable, "-m", "agentos_app.scripts.smoke", "--help"],
        cwd=str(_AGENT_RANK),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"smoke --help failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "AgentOS canonical-agent smoke" in (
        result.stdout + result.stderr
    )


# ---------------------------------------------------------------------
# T10-T13 — DOCUMENTED env-name reads must actually bind.
# Regression guard for the bug where `canonical_agent_id` was reading
# from `CANONICAL_AGENT_ID` (pydantic-settings default) instead of
# `AGENTOS_CANONICAL_AGENT_ID` per the documented contract.
# ---------------------------------------------------------------------


def _settings_from_env(env_overrides: dict[str, str]):
    """Construct AgentOSAppSettings under explicit env overrides.

    Uses ``monkeypatch``-style direct os.environ writes inside a try/
    finally so the test harness's environment is restored. Tests that
    use this helper are NOT compatible with the operator's local
    ``.env`` — `_env_file=None` disables that.
    """
    from agentos_app.config import AgentOSAppSettings

    saved: dict[str, str | None] = {}
    try:
        for k, v in env_overrides.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v
        return AgentOSAppSettings(_env_file=None)  # type: ignore[call-arg]
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_canonical_agent_id_env_override():
    """T10 — `AGENTOS_CANONICAL_AGENT_ID` env actually overrides default."""
    s = _settings_from_env(
        {"AGENTOS_CANONICAL_AGENT_ID": "custom_agent_t10"}
    )
    assert s.canonical_agent_id == "custom_agent_t10"

    # And a no-override run still returns the documented default.
    from agentos_app.config import AgentOSAppSettings

    # Strip the AGENTOS_CANONICAL_AGENT_ID var to make the negative case
    # deterministic regardless of the operator's local env.
    saved = os.environ.pop("AGENTOS_CANONICAL_AGENT_ID", None)
    try:
        s2 = AgentOSAppSettings(_env_file=None)  # type: ignore[call-arg]
        assert s2.canonical_agent_id == "swap_executor_v1"
    finally:
        if saved is not None:
            os.environ["AGENTOS_CANONICAL_AGENT_ID"] = saved


def test_llm_provider_and_model_env_override():
    """T11 — `AGENTOS_LLM_PROVIDER` + `AGENTOS_LLM_MODEL` overrides."""
    s = _settings_from_env(
        {
            "AGENTOS_LLM_PROVIDER": "anthropic",
            "AGENTOS_LLM_MODEL": "claude-haiku-4-5-20251001",
        }
    )
    assert s.llm_provider == "anthropic"
    assert s.llm_model == "claude-haiku-4-5-20251001"


def test_host_port_env_override():
    """T12 — `AGENTOS_HOST` + `AGENTOS_PORT` overrides at the settings layer.

    The Dockerfile's shell-form CMD also interpolates these vars into
    the uvicorn bind; static check below confirms that.
    """
    s = _settings_from_env(
        {"AGENTOS_HOST": "127.0.0.1", "AGENTOS_PORT": "9000"}
    )
    assert s.host == "127.0.0.1"
    assert s.port == 9000


def test_database_url_env_override():
    """T12c — `AGENTOS_DATABASE_URL` binds for live session storage."""
    s = _settings_from_env(
        {
            "AGENTOS_DATABASE_URL": (
                "postgresql+psycopg://proofarena:secret@postgres:5432/proof_arena"
            )
        }
    )
    assert (
        s.database_url
        == "postgresql+psycopg://proofarena:secret@postgres:5432/proof_arena"
    )


def test_agentos_db_factory_uses_postgres_session_table():
    """T12d — live AgentOS sessions use a Postgres-backed Agno DB."""
    from agentos_app.app import _build_db
    from agentos_app.config import AgentOSAppSettings

    settings = AgentOSAppSettings(
        database_url=(
            "postgresql+psycopg://proofarena:secret@postgres:5432/proof_arena"
        ),
        _env_file=None,
    )  # type: ignore[call-arg]

    db = _build_db(settings)
    assert db is not None
    assert (
        getattr(db, "session_table_name", None)
        == "proof_arena_agentos_sessions"
    )


def test_dockerfile_honors_host_port_env():
    """T12b — Dockerfile CMD interpolates `${AGENTOS_HOST}` / `${AGENTOS_PORT}`.

    Without this, the documented host/port settings are dead at the
    container boundary even if config.py reads them correctly.
    """
    dockerfile = (_AGENTOS_APP_DIR / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "${AGENTOS_HOST:-0.0.0.0}" in dockerfile, (
        "Dockerfile CMD must interpolate AGENTOS_HOST"
    )
    assert "${AGENTOS_PORT:-7000}" in dockerfile, (
        "Dockerfile CMD must interpolate AGENTOS_PORT"
    )
    # Negative guard: the old hardcoded form must not reappear.
    assert '"--host", "0.0.0.0", "--port", "7000"' not in dockerfile, (
        "Dockerfile must not hardcode --host/--port; use env "
        "interpolation so AGENTOS_HOST/AGENTOS_PORT actually drive bind"
    )


# ---------------------------------------------------------------------
# T14 — every provider in SUPPORTED_PROVIDERS imports cleanly under
# the agentos_app declared dependencies. Regression guard for the
# bug where the default openrouter path failed at AgentOS process
# startup with `ModuleNotFoundError: No module named 'openai'`.
# ---------------------------------------------------------------------


def test_supported_providers_importable_under_declared_deps():
    """T14 — agno provider modules for every entry in SUPPORTED_PROVIDERS
    must import cleanly using only agentos_app's declared dependencies.

    Agno's provider modules import their vendor SDK at module load
    time (e.g. `agno.models.openrouter` imports `openai.types.chat`).
    If any of these is missing from the runtime env, AgentOS process
    startup crashes at `_create_model()`. The agentos_app pyproject
    declares `openai`, `anthropic`, and `google-genai` to cover the
    four providers in `SUPPORTED_PROVIDERS`.
    """
    import importlib

    from agentos_app.agent import SUPPORTED_PROVIDERS

    expected = {"openrouter", "anthropic", "openai", "google"}
    assert set(SUPPORTED_PROVIDERS) == expected, (
        f"SUPPORTED_PROVIDERS drifted: {SUPPORTED_PROVIDERS}. "
        "If this set changes, update agentos_app/pyproject.toml deps "
        "to match (or narrow this test)."
    )

    for provider in SUPPORTED_PROVIDERS:
        module_name = f"agno.models.{provider}"
        try:
            importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError) as exc:
            raise AssertionError(
                f"Declared provider {provider!r} cannot import its "
                f"agno module {module_name!r}: {exc}. The vendor SDK "
                f"is missing from agentos_app's runtime dependencies."
            ) from exc


def test_vendor_keys_use_sdk_canonical_names():
    """T13 — Vendor keys read SDK-canonical names, NOT `AGENTOS_`-prefixed.

    Rationale: agno SDK reads these names natively + V1 backend env
    shares them. Double-prefixing would force operators to configure
    each key twice.
    """
    s = _settings_from_env(
        {
            "OPENROUTER_API_KEY": "or-test-t13",
            "ANTHROPIC_API_KEY": "anth-test-t13",
            "OPENAI_API_KEY": "oai-test-t13",
            "GOOGLE_API_KEY": "g-test-t13",
        }
    )
    assert s.openrouter_api_key == "or-test-t13"
    assert s.anthropic_api_key == "anth-test-t13"
    assert s.openai_api_key == "oai-test-t13"
    assert s.google_api_key == "g-test-t13"

    # Negative guard: AGENTOS_-prefixed vendor keys MUST NOT be honored
    # (would silently mislead operators who copy the prefix pattern).
    saved = os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ["AGENTOS_OPENROUTER_API_KEY"] = "wrong-prefix-t13"
    try:
        from agentos_app.config import AgentOSAppSettings

        s2 = AgentOSAppSettings(_env_file=None)  # type: ignore[call-arg]
        assert s2.openrouter_api_key == "", (
            "AGENTOS_OPENROUTER_API_KEY must not be honored — vendor "
            "keys use canonical SDK names without prefix"
        )
    finally:
        os.environ.pop("AGENTOS_OPENROUTER_API_KEY", None)
        if saved is not None:
            os.environ["OPENROUTER_API_KEY"] = saved
