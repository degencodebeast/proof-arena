import type { LeaderboardEntry } from '@/lib/types';

type BreakdownEntry = { value?: number; weight?: number };

const BREAKDOWN_LABELS: { key: string; label: string }[] = [
  { key: 'win_rate', label: 'Win Rate' },
  { key: 'execution_quality', label: 'Execution Quality' },
  { key: 'consistency', label: 'Consistency' },
  { key: 'confidence', label: 'Confidence' },
];

function getBreakdownValue(
  breakdown: Record<string, unknown> | undefined,
  key: string
): number | null {
  if (!breakdown) return null;
  const entry = breakdown[key];
  if (entry && typeof entry === 'object' && entry !== null) {
    const val = (entry as BreakdownEntry).value;
    if (typeof val === 'number' && isFinite(val)) return val;
  }
  return null;
}

export function AgentScoreCard({
  rank,
  breakdown,
}: {
  rank: LeaderboardEntry | null | undefined;
  breakdown?: Record<string, unknown>;
}) {
  if (!rank) {
    return (
      <div
        data-testid="score-card-no-rank"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-2"
      >
        <h3 className="text-lg font-semibold">AgentRank</h3>
        <p className="text-zinc-500 text-sm">
          No rank yet. This agent needs at least one completed challenge to
          appear on the leaderboard.
        </p>
      </div>
    );
  }

  return (
    <div
      data-testid="score-card"
      className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-5"
    >
      <div>
        <div className="flex items-baseline gap-2">
          <span className="text-5xl font-bold text-emerald-400">
            {rank.score.toFixed(2)}
          </span>
          <span className="text-zinc-500 text-sm">/ 100</span>
        </div>
        <p className="text-zinc-500 text-xs mt-1">
          AgentRank &middot; {rank.rank_version}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-zinc-500 text-xs">Wins</div>
          <div className="text-zinc-100 font-medium">{rank.wins}</div>
        </div>
        <div>
          <div className="text-zinc-500 text-xs">Losses</div>
          <div className="text-zinc-100 font-medium">{rank.losses}</div>
        </div>
        <div>
          <div className="text-zinc-500 text-xs">Completed</div>
          <div className="text-zinc-100 font-medium">{rank.completed_runs}</div>
        </div>
        <div>
          <div className="text-zinc-500 text-xs">Invalid</div>
          <div className="text-zinc-100 font-medium">{rank.invalid_runs}</div>
        </div>
      </div>

      <div className="space-y-2">
        <h4 className="text-zinc-300 text-sm font-medium">Score Breakdown</h4>
        {BREAKDOWN_LABELS.map(({ key, label }) => {
          const value = getBreakdownValue(breakdown, key);
          const pct = value == null ? 0 : Math.max(0, Math.min(100, value));
          return (
            <div key={key} data-testid={`breakdown-${key}`}>
              <div className="flex justify-between text-xs text-zinc-400 mb-1">
                <span>{label}</span>
                <span className="font-mono">
                  {value == null ? '—' : `${value.toFixed(1)}`}
                </span>
              </div>
              <div className="w-full h-1.5 bg-zinc-800 rounded">
                <div
                  className="h-full bg-emerald-500 rounded transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
