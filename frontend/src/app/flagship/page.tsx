'use client';

/**
 * Task 20 — public flagship page.
 *
 * Honest rendering of the current flagship state:
 *   - Flagship `AgentInstance` exists (Task 18 bootstrap).
 *   - Cron (Task 19) queues a benchmark Run every 6 hours.
 *   - Execution is deferred pending the runner swap-service abstraction,
 *     so runs currently appear as `pending`.
 *
 * The page does NOT imply completed execution. The "nothing filtered /
 * nothing staged" anchor from V2 spec §7 is preserved, with the hero
 * softened to acknowledge pending-execution reality.
 */

import { useQuery } from '@tanstack/react-query';
import { agentArenaApi } from '@/lib/api';
import type { FlagshipResponse } from '@/lib/types';

function isNotFound(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (error as any).response?.status === 404
  );
}

function formatCreatedAt(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

export default function FlagshipPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['flagship'],
    queryFn: async () => (await agentArenaApi.getFlagship()).data,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <p data-testid="flagship-loading" className="text-zinc-500">
          Loading flagship…
        </p>
      </div>
    );
  }

  if (isError && isNotFound(error)) {
    return (
      <div className="space-y-6">
        <div
          data-testid="flagship-empty"
          className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center"
        >
          <p className="text-zinc-400">No flagship instance yet.</p>
          <p className="text-zinc-500 text-sm mt-2">
            Run <code>scripts/bootstrap_flagship.py</code> then deploy via
            Task 18 to bring the canonical flagship online.
          </p>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="space-y-6">
        <p data-testid="flagship-error" className="text-red-400">
          Failed to load flagship.
        </p>
      </div>
    );
  }

  const flagship = data as FlagshipResponse;
  const od = flagship.outcome_distribution;

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold">Flagship</h1>
          <span
            data-testid="flagship-status-badge"
            className={
              flagship.status_label === 'devnet-live'
                ? 'inline-block px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-900/40 text-emerald-300 border border-emerald-800'
                : 'inline-block px-2 py-0.5 rounded-md text-xs font-medium bg-zinc-800 text-zinc-400 border border-zinc-700'
            }
          >
            {flagship.status_label}
          </span>
        </div>
        <p className="text-zinc-400 mt-2 max-w-2xl">
          Every six hours, a new benchmark run is logged for this flagship
          agent on Solana devnet. Below is the public record — nothing
          filtered, nothing staged. Per-run detail views land in a later task.
        </p>
      </div>

      {/* Outcome distribution strip */}
      <div
        data-testid="outcome-distribution"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-4"
      >
        <div className="flex items-center justify-between text-sm text-zinc-400 mb-2">
          <span>Recent outcomes ({od.total} runs)</span>
        </div>
        <div className="grid grid-cols-4 gap-3">
          <BucketCell
            label="complete"
            count={od.complete_count}
            pct={od.complete_pct}
            color="emerald"
            testId="outcome-complete-count"
          />
          <BucketCell
            label="invalid"
            count={od.invalid_count}
            pct={od.invalid_pct}
            color="amber"
            testId="outcome-invalid-count"
          />
          <BucketCell
            label="failed"
            count={od.failed_count}
            pct={od.failed_pct}
            color="rose"
            testId="outcome-failed-count"
          />
          <BucketCell
            label="pending"
            count={od.pending_count}
            pct={null}
            color="zinc"
            testId="outcome-pending-count"
          />
        </div>
      </div>

      {/* Recent runs list — unfiltered, newest-first */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Recent runs</h2>
        <ul
          data-testid="runs-list"
          className="bg-zinc-900 border border-zinc-800 rounded-xl divide-y divide-zinc-800"
        >
          {flagship.runs.length === 0 ? (
            <li className="p-4 text-zinc-500">No runs yet.</li>
          ) : (
            flagship.runs.map((r) => (
              <li
                key={r.run_id}
                data-testid={`run-row-${r.run_id}`}
                className="p-4 flex items-center justify-between gap-4"
              >
                <div className="flex flex-col gap-0.5 min-w-0">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-zinc-300 font-mono">
                      #{r.run_id}
                    </span>
                    <span className="text-zinc-500">·</span>
                    <span className="text-zinc-400">
                      {formatCreatedAt(r.created_at)}
                    </span>
                  </div>
                  {r.invalid_reason ? (
                    <span className="text-xs text-amber-400 mt-1">
                      {r.invalid_reason}
                    </span>
                  ) : null}
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <StatusPill
                    status={r.status}
                    completionStatus={r.completion_status}
                  />
                </div>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}

function BucketCell({
  label,
  count,
  pct,
  color,
  testId,
}: {
  label: string;
  count: number;
  pct: number | null;
  color: 'emerald' | 'amber' | 'rose' | 'zinc';
  testId: string;
}) {
  const colorMap: Record<string, string> = {
    emerald: 'text-emerald-300 bg-emerald-900/30 border-emerald-800',
    amber: 'text-amber-300 bg-amber-900/30 border-amber-800',
    rose: 'text-rose-300 bg-rose-900/30 border-rose-800',
    zinc: 'text-zinc-300 bg-zinc-800 border-zinc-700',
  };
  return (
    <div
      className={`rounded-lg border p-3 text-center ${colorMap[color]}`}
    >
      <div className="text-xs uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-semibold mt-1" data-testid={testId}>
        {count}
      </div>
      {pct !== null ? (
        <div className="text-xs opacity-75 mt-1">{pct.toFixed(1)}%</div>
      ) : null}
    </div>
  );
}

function StatusPill({
  status,
  completionStatus,
}: {
  status: string;
  completionStatus: string | null;
}) {
  // Render the RAW status + optional completion marker. No remapping.
  const completionText = completionStatus ? ` · ${completionStatus}` : '';
  return (
    <span className="inline-block px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700 font-mono">
      {status}
      {completionText}
    </span>
  );
}
