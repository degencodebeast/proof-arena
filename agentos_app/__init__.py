"""Proof Arena product-owned AgentOS service.

This package is the Coolify-deployed AgentOS process described in
``.taskmaster/docs/task12-agentos-contract-note.md`` §3 ("Operationally,
this is a small product-owned Python module outside ``backend/src/``").
It runs ``agno.os.AgentOS(agents=[swap_executor_agent]).get_app()`` so
the canonical V2 agent is pre-registered at process startup. The
backend reaches it via ``AGENTOS_API_URL`` and creates per-instance
sessions against ``AGENTOS_CANONICAL_AGENT_ID``.

Decision-only contract (V2 trust boundary): the agent does not own
wallets, call Orca, or execute swaps. It returns structured
``AgentAction`` content; the backend runner validates, executes via
platform-owned adapters, records evidence, and scores the run.

Single source of truth: ``SWAP_EXECUTOR_V1_SEED`` is imported verbatim
from ``backend/src/services/template_service.py`` via
``canonical_template_contract``. Forking that dict here is forbidden.
"""
