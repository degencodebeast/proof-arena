import Link from 'next/link';
import type { ContestantSummary } from '@/lib/types';

export function ContestantsList({
  contestants,
  winnerAgentId,
}: {
  contestants?: ContestantSummary[];
  winnerAgentId?: number | null;
}) {
  if (!contestants || contestants.length === 0) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
        <h3 className="text-lg font-semibold mb-4">Contestants</h3>
        <p data-testid="empty-contestants" className="text-zinc-500 text-sm">
          No contestants.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
      <h3 className="text-lg font-semibold mb-4">Contestants</h3>
      <div className="space-y-3">
        {contestants.map((c) => {
          const isWinner = winnerAgentId != null && c.agent_id === winnerAgentId;
          return (
            <div
              key={c.agent_id}
              data-testid={`contestant-${c.agent_id}`}
              className={`p-3 rounded-lg border ${
                isWinner
                  ? 'border-emerald-600 bg-emerald-900/20'
                  : 'border-zinc-800 bg-zinc-800/50'
              }`}
            >
              <div className="flex justify-between items-center">
                <span className="font-medium">
                  <Link
                    href={`/agents/${c.agent_id}`}
                    className="hover:text-emerald-400 transition"
                  >
                    {c.display_name}
                  </Link>
                  {isWinner && (
                    <span
                      data-testid="winner-badge"
                      className="ml-2 text-emerald-400 text-xs font-mono"
                    >
                      WINNER
                    </span>
                  )}
                </span>
                <span className="text-xs text-zinc-500">{c.status}</span>
              </div>
              {c.ending_value != null && (
                <p className="text-sm text-zinc-400 mt-1">
                  Ending: {(c.ending_value / 1_000_000).toFixed(2)} USDC
                </p>
              )}
              {c.completion_status && (
                <span
                  className={`text-xs ${
                    c.completion_status === 'complete'
                      ? 'text-emerald-400'
                      : c.completion_status === 'invalid'
                        ? 'text-red-400'
                        : 'text-yellow-400'
                  }`}
                >
                  {c.completion_status}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
