"""AgentOS runtime implementation — session-backed wrapper.

This is the ONE and ONLY V2 file allowed to import ``agno`` / ``agno.client``
per V2 plan invariant 4 ("runtime import boundary"). Enforced by the
AST-walk guard test in ``tests/test_task_12_import_boundary.py``.

V2 model (see ``.taskmaster/docs/task12-agentos-contract-note.md``):
- AgentOS is a shared, self-hosted runtime substrate.
- Canonical agents (e.g. ``swap_executor_v1``) are pre-registered at
  AgentOS process startup. The client cannot create or delete agents at
  runtime.
- Per-instance runtime isolation is **session-based**: each hosted
  instance (flagship + user-deployed) gets its own AgentOS session on
  the shared canonical agent.
- ``AgentOSRuntime.deploy(spec)`` creates a session.
  ``AgentOSRuntime.invoke_decide(handle, state)`` runs the agent within
  that session. ``AgentOSRuntime.teardown(handle)`` deletes the session.
  The canonical agent is never touched.

Error boundary: no ``agno`` or Pydantic exception types cross this
module's public surface. All failures become ``AgentOSRuntimeError``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agno.client import AgentOSClient  # noqa: F401 — the single allowed V2 AgentOS import

from src.db.schemas import AgentAction
from src.runtime.base import InstanceHandle, InstanceSpec

logger = logging.getLogger(__name__)


class AgentOSRuntimeError(Exception):
    """Local error type for the AgentOS runtime wrapper.

    Every failure that crosses the runtime boundary is an instance of
    this type. No Agno / Pydantic exceptions are surfaced to callers.
    """


# Schema for structured output — AgentOS ``run_agent`` supports
# ``output_schema`` as a documented ``**kwargs`` passthrough (contract note §1).
# We compute it once at import time from the Pydantic model.
_AGENT_ACTION_JSON_SCHEMA: dict[str, Any] = AgentAction.model_json_schema()


class AgentOSRuntime:
    """Session-backed AgentOS runtime.

    Structurally satisfies the ``InstanceRuntime`` protocol in
    ``src.runtime.base``. Not a subclass — Protocol conformance is duck-typed.
    """

    def __init__(
        self,
        api_url: str,
        auth_token: str = "",
        canonical_agent_ids: dict[str, str] | None = None,
        # Back-compat: legacy callers pass a single string; promoted to dict.
        canonical_agent_id: str = "",
        use_output_schema: bool = False,
    ) -> None:
        if not api_url:
            raise ValueError(
                "AgentOSRuntime: api_url must be set "
                "(see settings.AGENTOS_API_URL)."
            )

        # Back-compat: if the dict isn't passed but the legacy string is,
        # promote it to a {swap_executor_v1: id} dict.
        if canonical_agent_ids is None:
            if not canonical_agent_id:
                raise ValueError(
                    "AgentOSRuntime: canonical_agent_ids dict OR canonical_agent_id "
                    "must be set. Configure at least the swap_executor_v1 canonical agent id."
                )
            canonical_agent_ids = {"swap_executor_v1": canonical_agent_id}

        if not canonical_agent_ids:
            raise ValueError(
                "AgentOSRuntime: canonical_agent_ids dict must be non-empty "
                "(keyed by template_key). Configure at least swap_executor_v1."
            )

        self._client = AgentOSClient(base_url=api_url)
        self._canonical_agent_ids: dict[str, str] = dict(canonical_agent_ids)
        # Empty token -> no Authorization header (private network deployments).
        self._auth_headers: dict[str, str] | None = (
            {"Authorization": f"Bearer {auth_token}"} if auth_token else None
        )
        # Structured-output (output_schema kwarg) is provider-dependent. Pre-
        # Task-13 live gate observed OpenRouter-routed OpenAI models failing
        # with ``status='ERROR'`` / ``content='Provider returned error'`` when
        # output_schema was passed. Default OFF so the wrapper survives the
        # common configuration; opt in only when the configured model is
        # known to handle Agno's structured-output translation. Prompt-
        # contract + Python-side JSON parse (str branch of
        # ``_parse_agent_action``) works regardless.
        self._use_output_schema = use_output_schema

    # -------------------------------------------------------------------
    # deploy — create a session on the canonical agent
    # -------------------------------------------------------------------

    async def deploy(self, spec: InstanceSpec) -> InstanceHandle:
        """Create a new AgentOS session; return an InstanceHandle.

        Does NOT provision a new remote agent (AgentOS has no such API).

        Dispatches to the canonical agent registered for ``spec.template_key``.
        Raises ``AgentOSRuntimeError`` if the template_key has no registered
        canonical agent id.

        Persists ``spec.effective_config`` in ``InstanceHandle.extra`` so the
        customization envelope survives the DB round-trip and reaches each
        ``invoke_decide`` call. Session-level isolation + per-message config
        injection is how V2 applies per-instance customization on top of a
        shared canonical agent.
        """
        agent_id = self._canonical_agent_ids.get(spec.template_key)
        if not agent_id:
            raise AgentOSRuntimeError(
                f"unknown template_key {spec.template_key!r}; "
                f"canonical_agent_ids covers {sorted(self._canonical_agent_ids.keys())}"
            )
        try:
            session = await self._client.create_session(
                agent_id=agent_id,
                user_id=spec.instance_owner_ref,
                session_name=f"{spec.template_key}:{spec.template_version}",
                headers=self._auth_headers,
            )
        except Exception as e:  # noqa: BLE001 — translate all SDK errors
            raise AgentOSRuntimeError(
                f"create_session failed: {e}"
            ) from e

        session_id = getattr(session, "session_id", None)
        if not session_id:
            raise AgentOSRuntimeError(
                "create_session returned an object without session_id; "
                "AgentOS SDK contract violated."
            )

        return InstanceHandle(
            instance_id=agent_id,
            extra={
                "session_id": session_id,
                "effective_config": dict(spec.effective_config),
            },
        )

    # -------------------------------------------------------------------
    # invoke_decide — run the canonical agent within the instance's session
    # -------------------------------------------------------------------

    async def invoke_decide(
        self, handle: InstanceHandle, state: Any
    ) -> AgentAction:
        """Call ``run_agent`` and parse its content into an ``AgentAction``."""
        session_id = handle.extra.get("session_id") if handle.extra else None
        if not session_id:
            raise AgentOSRuntimeError(
                "invoke_decide: handle.extra['session_id'] missing; "
                "deploy() must be called first."
            )

        effective_config = (
            handle.extra.get("effective_config") if handle.extra else None
        ) or {}
        run_kwargs: dict[str, Any] = {
            "agent_id": handle.instance_id,
            "message": self._serialize_state(state, effective_config),
            "session_id": session_id,
            "headers": self._auth_headers,
        }
        if self._use_output_schema:
            run_kwargs["output_schema"] = _AGENT_ACTION_JSON_SCHEMA
        try:
            result = await self._client.run_agent(**run_kwargs)
        except Exception as e:  # noqa: BLE001 — translate all SDK errors
            raise AgentOSRuntimeError(
                f"run_agent failed: {e}"
            ) from e

        return self._parse_agent_action(result)

    # -------------------------------------------------------------------
    # teardown — delete the session (idempotent)
    # -------------------------------------------------------------------

    async def teardown(self, handle: InstanceHandle) -> None:
        """Delete the session. Idempotent on 'not found'."""
        session_id = handle.extra.get("session_id") if handle.extra else None
        if not session_id:
            return  # idempotent no-op

        try:
            await self._client.delete_session(
                session_id=session_id,
                headers=self._auth_headers,
            )
        except Exception as e:  # noqa: BLE001 — narrow below
            if _is_session_not_found(e):
                logger.debug(
                    "teardown: session %s already gone (idempotent).",
                    session_id,
                )
                return
            raise AgentOSRuntimeError(
                f"delete_session failed: {e}"
            ) from e

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _serialize_state(state: Any, effective_config: dict[str, Any] | None = None) -> str:
        """Serialize a ChallengeState + instance config into a prompt message.

        Deterministic: both sections are sorted-key JSON so evidence hashes
        stay stable across runs.

        Message contract (stable):

            Instance config (JSON):
            {<sorted effective_config>}

            Challenge state (JSON):
            {<sorted state>}

            Return a single AgentAction JSON object with the fields
            {type, params} per the output_schema.
        """
        if hasattr(state, "__dict__"):
            state_payload = {
                k: v for k, v in state.__dict__.items() if not k.startswith("_")
            }
        elif isinstance(state, dict):
            state_payload = state
        else:
            state_payload = {"state": repr(state)}

        try:
            state_body = json.dumps(state_payload, default=str, sort_keys=True)
        except (TypeError, ValueError):
            state_body = json.dumps({"state": repr(state)})

        cfg = effective_config or {}
        try:
            cfg_body = json.dumps(cfg, default=str, sort_keys=True)
        except (TypeError, ValueError):
            cfg_body = json.dumps({"effective_config": repr(cfg)})

        return (
            "Instance config (JSON):\n"
            f"{cfg_body}\n\n"
            "Challenge state (JSON):\n"
            f"{state_body}\n"
            "Return a single AgentAction JSON object with the fields "
            "{type, params} per the output_schema."
        )

    @staticmethod
    def _parse_agent_action(result: Any) -> AgentAction:
        """Dual-branch parse of ``run_agent`` output into an AgentAction.

        Edge-case spec §8: content may be a dict (when ``output_schema`` is
        honored server-side as structured output) OR a JSON-encoded string
        (when it's returned as raw text). Handle both.
        """
        if result is None:
            raise AgentOSRuntimeError("run_agent returned None; empty response.")

        # Live gate evidence: provider-side failures surface as
        # ``status='ERROR'`` with a human-readable message in ``content``.
        # Raise a clear diagnostic INSTEAD of attempting a JSON parse that
        # would fail with a misleading error.
        status = getattr(result, "status", None)
        status_str = getattr(status, "value", status)
        if status_str == "ERROR":
            detail = getattr(result, "content", None) or "<no detail>"
            raise AgentOSRuntimeError(
                f"run_agent returned status=ERROR: {detail}"
            )

        content = getattr(result, "content", None)
        if content is None or content == "":
            raise AgentOSRuntimeError("run_agent result.content is empty.")

        if isinstance(content, AgentAction):
            return content

        try:
            if isinstance(content, dict):
                return AgentAction.model_validate(content)
            if isinstance(content, str):
                return AgentAction.model_validate_json(content.strip())
        except Exception as e:  # noqa: BLE001 — Pydantic ValidationError + JSON errors
            raise AgentOSRuntimeError(
                f"failed to parse AgentAction from run_agent content: {e}"
            ) from e

        raise AgentOSRuntimeError(
            f"run_agent returned unsupported content type: {type(content).__name__}"
        )


def _is_session_not_found(exc: Exception) -> bool:
    """Heuristic for idempotent-teardown on already-deleted session.

    Narrow substring match on the exception message. The real Agno error
    class for this case is not yet pinned; when it is, tighten here.
    """
    text = str(exc).lower()
    return "not found" in text or "404" in text
