'use client';

/**
 * Task 24 — owner-scoped instance dashboard.
 *
 * Reads from Task 17's `GET /api/v1/instances/{instance_id}` (owner-gated).
 * Renders honestly against the shipped flat response: no nested
 * `lineage` dict, no fabricated Benchmark-now button (no HTTP surface
 * exists for user-triggered benchmarks in V2 — see Task 24 spec §1).
 *
 * Supersession is displayed via a top-of-page banner pointing at
 * `superseded_by_instance_id`; the old row's `status` column is NOT
 * mutated and the pill continues to render the raw value (Task 28
 * FK-only contract).
 */

import { useQuery } from '@tanstack/react-query';
import { usePrivy } from '@privy-io/react-auth';
import { useParams } from 'next/navigation';
import Link from 'next/link';

import { agentArenaApi } from '@/lib/api';
import type { InstanceProfileResponse } from '@/lib/types';
import {
  TRUST_LABELS,
  type TrustLabel,
  getTrustLabelDisplay,
} from '@/lib/trustLabels';

function statusFromError(err: unknown): number | null {
  if (typeof err !== 'object' || err === null || !('response' in err)) {
    return null;
  }
  const resp = (err as { response?: { status?: number } }).response;
  return typeof resp?.status === 'number' ? resp.status : null;
}

function formatCreatedAt(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

function isKnownTrustLabel(label: string): label is TrustLabel {
  return label in TRUST_LABELS;
}

function AuthPrompt({ onLogin }: { onLogin: () => void }) {
  return (
    <div
      data-testid="auth-prompt"
      className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-4"
    >
      <p className="text-zinc-300">Sign in to view your hosted instance.</p>
      <button
        onClick={onLogin}
        className="inline-block px-4 py-2 rounded-md bg-emerald-700 hover:bg-emerald-600 text-white text-sm font-medium"
      >
        Sign in
      </button>
    </div>
  );
}

export default function InstanceDashboardPage() {
  const params = useParams<{ id: string }>();
  const instanceId = Number(params.id);
  const hasValidInstanceId = Number.isFinite(instanceId) && instanceId > 0;

  const { authenticated, getAccessToken, login } = usePrivy();

  const { data, isLoading, isError, error } = useQuery<InstanceProfileResponse>({
    queryKey: ['instance', instanceId],
    enabled: authenticated && hasValidInstanceId,
    queryFn: async () => {
      const token = await getAccessToken();
      if (!token) throw new Error('auth-missing');
      const res = await agentArenaApi.getInstance(instanceId, token);
      return res.data;
    },
    retry: false,
  });

  // Guard invalid route params before dereferencing `data` below. The
  // previous `const instance = data!` path crashed with TypeError when
  // `params.id = "foo"` → Number("foo") = NaN → enabled=false → data=undefined.
  if (!hasValidInstanceId) {
    return (
      <div
        data-testid="instance-invalid-id"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-2"
      >
        <p className="text-zinc-300">Invalid instance id.</p>
        <p className="text-zinc-500 text-sm">
          Instance ids must be positive integers.
        </p>
      </div>
    );
  }

  if (!authenticated) {
    return <AuthPrompt onLogin={() => login()} />;
  }

  if (isLoading) {
    return (
      <p data-testid="instance-loading" className="text-zinc-500">
        Loading instance…
      </p>
    );
  }

  if (isError) {
    const status = statusFromError(error);
    if (status === 401) {
      // Token rejected / expired — route to auth prompt rather than
      // generic error so the user can re-authenticate.
      return <AuthPrompt onLogin={() => login()} />;
    }
    if (status === 403) {
      return (
        <div
          data-testid="instance-forbidden"
          className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-2"
        >
          <p className="text-zinc-300">Not your instance.</p>
          <p className="text-zinc-500 text-sm">
            This instance belongs to another owner.
          </p>
        </div>
      );
    }
    if (status === 404) {
      return (
        <div
          data-testid="instance-not-found"
          className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-2"
        >
          <p className="text-zinc-300">Instance not found.</p>
        </div>
      );
    }
    return (
      <p data-testid="instance-error" className="text-red-400">
        Failed to load instance. Please try again.
      </p>
    );
  }

  const instance = data!;
  const trustLabelDisplay = isKnownTrustLabel(instance.trust_label)
    ? getTrustLabelDisplay(instance.trust_label)
    : instance.trust_label;

  return (
    <div className="space-y-6">
      {instance.is_superseded && instance.superseded_by_instance_id !== null ? (
        <div
          data-testid="supersede-banner"
          className="bg-amber-950/40 border border-amber-900 rounded-xl p-4 text-amber-200"
        >
          <div className="flex items-center justify-between gap-4">
            <div className="text-sm">
              This configuration was replaced by instance{' '}
              <span className="font-mono">
                #{instance.superseded_by_instance_id}
              </span>
              . Benchmark history below is frozen.
            </div>
            <Link
              href={`/instances/${instance.superseded_by_instance_id}`}
              className="text-xs text-amber-300 underline underline-offset-2 hover:text-amber-200"
            >
              Open replacement →
            </Link>
          </div>
        </div>
      ) : null}

      {/* Header */}
      <div data-testid="instance-header">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-3xl font-bold">
            Instance <span className="font-mono">#{instance.instance_id}</span>
          </h1>
          <span
            data-testid="trust-label-badge"
            className="inline-block px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-900/40 text-emerald-300 border border-emerald-800"
          >
            {trustLabelDisplay}
          </span>
          <span
            data-testid="saga-status-pill"
            className="inline-block px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700 font-mono text-xs"
          >
            {instance.status}
          </span>
        </div>
        {instance.last_failure_reason ? (
          <p
            data-testid="last-failure-reason"
            className="text-amber-400 text-sm mt-2"
          >
            Last failure: {instance.last_failure_reason}
          </p>
        ) : null}
        <p
          data-testid="template-metadata"
          className="text-zinc-500 text-sm mt-2"
        >
          Template{' '}
          <span className="font-mono text-zinc-300">
            {instance.template_key ?? 'unknown'}
          </span>
          {' · template_version_at_deploy '}
          <span className="font-mono text-zinc-300">
            {instance.template_version_at_deploy}
          </span>
          {' · deployed '}
          <span className="font-mono text-zinc-300">
            {formatCreatedAt(instance.created_at)}
          </span>
        </p>
      </div>

      {/* Configuration — read-only */}
      <div
        data-testid="config-panel"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-4"
      >
        <h2 className="text-lg font-semibold mb-3">Configuration</h2>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          {Object.entries(instance.effective_config).map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="text-zinc-500 font-mono text-xs">{key}</dt>
              <dd className="text-zinc-300 font-mono text-sm break-words">
                {Array.isArray(value)
                  ? value.map((v) => String(v)).join(', ')
                  : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Benchmark history */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Benchmark history</h2>
        {!instance.benchmarked ? (
          <div
            data-testid="benchmark-empty"
            className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-2"
          >
            <p className="text-zinc-300">Not yet benchmarked.</p>
            <p className="text-zinc-500 text-sm">
              Results will appear here once a scheduled benchmark completes.
            </p>
          </div>
        ) : (
          <>
            <ul
              data-testid="runs-list"
              className="bg-zinc-900 border border-zinc-800 rounded-xl divide-y divide-zinc-800"
            >
              {instance.runs.map((r) => (
                <li
                  key={r.run_id}
                  data-testid={`instance-run-row-${r.run_id}`}
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
                  <div className="flex items-center gap-3 text-xs">
                    {r.ending_value !== null ? (
                      <span className="text-zinc-400 font-mono">
                        ending {r.ending_value.toLocaleString()}
                      </span>
                    ) : null}
                    <span className="inline-block px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700 font-mono">
                      {r.status}
                      {r.completion_status ? ` · ${r.completion_status}` : ''}
                    </span>
                  </div>
                </li>
              ))}
            </ul>

            {instance.rank_history.length > 0 ? (
              <div className="mt-6">
                <h3 className="text-sm font-semibold mb-2 text-zinc-300">
                  Rank history
                </h3>
                <ul
                  data-testid="rank-list"
                  className="bg-zinc-900 border border-zinc-800 rounded-xl divide-y divide-zinc-800"
                >
                  {instance.rank_history.map((s) => (
                    <li
                      key={s.snapshot_id}
                      data-testid={`instance-rank-row-${s.snapshot_id}`}
                      className="p-4 flex items-center justify-between gap-4 text-sm"
                    >
                      <div className="flex flex-col gap-0.5">
                        <span className="text-zinc-300 font-mono">
                          score {s.score.toFixed(1)}
                        </span>
                        <span className="text-zinc-500 text-xs">
                          wins {s.wins} · losses {s.losses} · completed{' '}
                          {s.completed_runs} · invalid {s.invalid_runs}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-zinc-500">
                          {formatCreatedAt(s.computed_at)}
                        </span>
                        <span className="inline-block px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700 font-mono">
                          {s.subject_type}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
