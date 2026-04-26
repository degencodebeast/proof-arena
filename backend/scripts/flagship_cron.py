"""flagship_cron.py — Task 19 / plan D-2, execution wiring per Task 37.

Scheduled flagship benchmark orchestration — creation AND execution.

On each tick the cron:
- acquires a POSIX non-blocking exclusive lock (overlap guard),
- opens an async DB session,
- resolves the flagship ``AgentInstance`` via
  ``FlagshipService.get_flagship_instance()`` (Task 18 contract),
- creates a ``Run`` row via
  ``ChallengeService.create_run_for_instance()`` (Task 15 contract),
- **executes the run** via ``RunnerService.execute_run(run, challenge,
  provider)`` over the V2 hosted path (Task 37): ``OrcaSwapService``
  as the ``SwapServiceProtocol`` implementation +
  ``HostedInstanceProvider(AgentOSRuntime, InstanceHandle)`` as the
  ``AgentDecisionProvider``,
- releases the lock.

Task 37 lifted the prior creation-only boundary. ``RunnerService``
is now protocol-typed via ``SwapServiceProtocol``; the flagship cron
constructs ``OrcaSwapService`` so the hosted path stays Orca-only
(V2 plan §10 invariant "no Jupiter reintroduction in active hosted
V2 paths").

Usage::

    python scripts/flagship_cron.py --challenge-id 42
    python scripts/flagship_cron.py --challenge-id 42 --template-key swap_executor_v1

POSIX-only (``fcntl.flock``). macOS/Linux VPS targets per Task 29.

Exit codes:
    0 — tick completed OR another tick is in progress (lock contention)
    1 — unexpected failure (flagship missing, challenge missing,
        execute_run raised, etc.). The created Run row is NOT rolled back
        on execute_run failure — its status reflects whatever the runner
        persisted.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.engine import async_session_factory
from src.providers.hosted_instance_provider import HostedInstanceProvider
from src.runtime.agentos import AgentOSRuntime
from src.runtime.base import InstanceHandle
from src.services.challenge_service import ChallengeService
from src.services.flagship_service import FlagshipService
from src.services.runner_service import RunnerService
from src.services.swap_service import OrcaSwapService
from src.services.wallet_service import WalletService

logger = logging.getLogger(__name__)

_DEFAULT_LOCK_PATH = "/tmp/flagship_cron.lock"
_DEFAULT_TEMPLATE_KEY = "swap_executor_v1"


# ---------------------------------------------------------------------
# Lock helpers — extracted for tests
# ---------------------------------------------------------------------


def _acquire_lock(path: str):
    """Attempt POSIX non-blocking exclusive lock. Return fd on success, None on contention.

    Caller MUST call ``_release_lock`` on the returned fd to release the
    lock cleanly (success, failure, or exception).
    """
    fd = open(path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        return None
    return fd


def _release_lock(fd) -> None:
    """Release lock + close fd. Safe to call on a None fd (no-op)."""
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        fd.close()


# ---------------------------------------------------------------------
# Tick — pure orchestration, dependency-injected DB session
# ---------------------------------------------------------------------


async def _run_flagship_tick(
    db: AsyncSession, *, challenge_id: int, template_key: str
) -> int:
    """Run one end-to-end flagship tick against the given session.

    Flow:
    1. Resolve flagship via ``FlagshipService.get_flagship_instance``.
    2. Create pending Run via ``ChallengeService.create_run_for_instance``.
    3. Execute the Run via ``RunnerService.execute_run`` over the V2
       hosted path (``OrcaSwapService`` + ``HostedInstanceProvider``).

    Returns exit code 0 on full success, 1 on any domain error. On
    execution failure, the created Run row is NOT rolled back — its
    status reflects whatever ``execute_run`` persisted.
    """
    flagship_service = FlagshipService(db)
    flagship = await flagship_service.get_flagship_instance(template_key=template_key)
    if flagship is None:
        logger.warning(
            "flagship_cron: no live flagship instance for template %r — "
            "run scripts/bootstrap_flagship.py then redeploy via Task 18; "
            "skipping tick",
            template_key,
        )
        return 1

    challenge_service = ChallengeService(db, program_client=None)
    try:
        run = await challenge_service.create_run_for_instance(
            instance_id=flagship.instance_id,
            challenge_config={"challenge_id": challenge_id},
        )
    except ValueError as exc:
        # Both "Challenge X not found" and "Run ... already exists" surface
        # as ValueError from ChallengeService — log the specific message
        # and exit with non-zero so systemd/cron flags the run.
        logger.error(
            "flagship_cron: could not create run for flagship=%s challenge=%s: %s",
            flagship.instance_id,
            challenge_id,
            exc,
        )
        return 1

    # Load challenge row + deserialize the opaque runtime handle.
    challenge = await challenge_service.get_by_id(challenge_id)
    if challenge is None:
        logger.error("flagship_cron: challenge %s vanished mid-tick", challenge_id)
        return 1
    try:
        handle = InstanceHandle(**json.loads(flagship.runtime_handle_json or "{}"))
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(
            "flagship_cron: flagship instance %s has unparseable runtime_handle_json: %s",
            flagship.instance_id,
            exc,
        )
        return 1

    # Build the V2 hosted stack.
    runtime = AgentOSRuntime(
        api_url=settings.AGENTOS_API_URL,
        auth_token=settings.AGENTOS_AUTH_TOKEN,
        canonical_agent_id=settings.AGENTOS_CANONICAL_AGENT_ID,
    )
    provider = HostedInstanceProvider(runtime, handle)
    swap_service = OrcaSwapService(
        rpc_url=settings.SOLANA_RPC_URL,
        cluster=settings.SOLANA_CLUSTER,
        pool_address=settings.V2_HOSTED_SWAP_POOL,
    )
    wallet_service = WalletService()

    # Execute. Failures leave the Run row committed with whatever status
    # the runner persisted (e.g., "failed" / "timeout" / "completed").
    try:
        await RunnerService(
            db,
            swap_service,
            wallet_service,
        ).execute_run(run, challenge, provider)
    except Exception as exc:  # noqa: BLE001 — log + non-zero exit for systemd
        logger.exception(
            "flagship_cron: execute_run failed for run_id=%s flagship_instance=%s: %s",
            run.run_id,
            flagship.instance_id,
            exc,
        )
        return 1

    logger.info(
        "flagship_cron: executed run_id=%s for flagship_instance=%s "
        "challenge=%s (final status=%s)",
        run.run_id,
        flagship.instance_id,
        challenge_id,
        run.status,
    )
    return 0


# ---------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------


def main(
    template_key: str = _DEFAULT_TEMPLATE_KEY,
    *,
    challenge_id: int,
    lock_path: str = _DEFAULT_LOCK_PATH,
) -> int:
    """CLI wrapper — acquire lock, run tick, release lock.

    Returns process exit code. Lock contention is NOT an error: the cron
    scheduler is expected to re-fire on the next cadence tick. Only
    domain-level failures exit non-zero.
    """
    fd = _acquire_lock(lock_path)
    if fd is None:
        logger.info(
            "flagship_cron: another tick is in progress "
            "(lock=%s); skipping this cadence",
            lock_path,
        )
        return 0

    try:
        async def _tick() -> int:
            async with async_session_factory() as session:
                return await _run_flagship_tick(
                    session,
                    challenge_id=challenge_id,
                    template_key=template_key,
                )

        return asyncio.run(_tick())
    except Exception as exc:  # noqa: BLE001 — log + exit cleanly
        logger.exception("flagship_cron: unexpected failure: %s", exc)
        return 1
    finally:
        _release_lock(fd)


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--challenge-id",
        type=int,
        required=True,
        help="Existing Challenge row id (operator-created via admin).",
    )
    parser.add_argument("--template-key", default=_DEFAULT_TEMPLATE_KEY)
    parser.add_argument("--lock-path", default=_DEFAULT_LOCK_PATH)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return main(
        template_key=args.template_key,
        challenge_id=args.challenge_id,
        lock_path=args.lock_path,
    )


if __name__ == "__main__":
    sys.exit(_cli())
