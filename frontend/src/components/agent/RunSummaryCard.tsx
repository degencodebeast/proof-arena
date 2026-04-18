import Link from 'next/link';
import type { RunSummary } from '@/lib/types';

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-zinc-700 text-zinc-300',
  running: 'bg-emerald-900 text-emerald-300',
  completed: 'bg-blue-900 text-blue-300',
  failed: 'bg-red-900 text-red-300',
  timeout: 'bg-orange-900 text-orange-300',
};

const COMPLETION_STYLES: Record<string, string> = {
  complete: 'text-emerald-400',
  incomplete: 'text-yellow-400',
  invalid: 'text-red-400',
};

function formatUsdc(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${(value / 1_000_000).toFixed(2)} USDC`;
}

export function RunSummaryCard({ run }: { run: RunSummary }) {
  return (
    <div
      data-testid={`run-card-${run.run_id}`}
      className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-2"
    >
      <div className="flex justify-between items-center">
        <Link
          href={`/challenges/${run.challenge_id}`}
          className="text-emerald-400 hover:underline text-sm font-medium"
        >
          Challenge #{run.challenge_id}
        </Link>
        <span
          data-testid={`run-status-${run.run_id}`}
          className={`px-2 py-0.5 rounded text-xs font-medium ${
            STATUS_STYLES[run.status] ?? 'bg-zinc-700 text-zinc-400'
          }`}
        >
          {run.status}
        </span>
      </div>

      <div className="flex justify-between text-xs text-zinc-400">
        <span>
          Starting: <span className="text-zinc-200">{formatUsdc(run.starting_value)}</span>
        </span>
        <span>
          Ending: <span className="text-zinc-200">{formatUsdc(run.ending_value)}</span>
        </span>
      </div>

      {run.completion_status && (
        <div
          data-testid={`run-completion-${run.run_id}`}
          className={`text-xs ${
            COMPLETION_STYLES[run.completion_status] ?? 'text-zinc-400'
          }`}
        >
          {run.completion_status}
        </div>
      )}
    </div>
  );
}
