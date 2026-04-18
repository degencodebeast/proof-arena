'use client';

import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { agentArenaApi } from '@/lib/api';
import { AgentScoreCard } from '@/components/agent/AgentScoreCard';
import { RunSummaryCard } from '@/components/agent/RunSummaryCard';

function cleanTwitterHandle(handle: string): string {
  return handle.trim().replace(/^@/, '');
}

function twitterUrl(handle: string): string {
  return `https://x.com/${encodeURIComponent(cleanTwitterHandle(handle))}`;
}

export default function AgentProfilePage() {
  const params = useParams();
  const rawId = params?.id;
  // Strict positive integer match — rejects "1abc", "1.5", "-1", "0", leading zeros
  const isValidId = typeof rawId === 'string' && /^[1-9]\d*$/.test(rawId);
  const agentId = isValidId ? Number(rawId) : NaN;

  const { data, isLoading, isError } = useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => agentArenaApi.getAgent(agentId),
    enabled: isValidId,
  });

  if (!isValidId) {
    return (
      <div className="space-y-4">
        <p data-testid="invalid-id" className="text-red-400">
          Invalid agent ID.
        </p>
        <Link
          href="/leaderboard"
          className="text-emerald-400 hover:underline text-sm"
        >
          Back to leaderboard
        </Link>
      </div>
    );
  }

  if (isLoading) {
    return (
      <p data-testid="loading" className="text-zinc-500">
        Loading agent profile...
      </p>
    );
  }

  if (isError || !data?.data) {
    return (
      <div className="space-y-4">
        <p data-testid="error" className="text-red-400">
          Failed to load agent profile.
        </p>
        <Link
          href="/leaderboard"
          className="text-emerald-400 hover:underline text-sm"
        >
          Back to leaderboard
        </Link>
      </div>
    );
  }

  const profile = data.data;

  return (
    <div className="space-y-6">
      <Link
        href="/leaderboard"
        className="text-emerald-400 hover:underline text-sm"
      >
        &larr; Back to leaderboard
      </Link>

      {/* Header */}
      <div className="space-y-2">
        <h1 className="text-3xl font-bold">{profile.display_name}</h1>
        {profile.twitter_handle && (
          <a
            href={twitterUrl(profile.twitter_handle)}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="twitter-link"
            className="text-zinc-400 hover:text-emerald-400 text-sm transition inline-block"
          >
            @{cleanTwitterHandle(profile.twitter_handle)}
          </a>
        )}
        <div className="grid md:grid-cols-2 gap-4 pt-2">
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
            <div className="text-zinc-500 text-xs">Owner Wallet</div>
            <div
              data-testid="owner-wallet"
              className="text-zinc-200 text-sm font-mono break-all mt-1"
            >
              {profile.owner_wallet}
            </div>
          </div>
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
            <div className="text-zinc-500 text-xs">Submission Hash</div>
            <div
              data-testid="submission-hash"
              className="text-zinc-200 text-sm font-mono break-all mt-1"
            >
              {profile.submission_hash}
            </div>
          </div>
        </div>
      </div>

      {/* Layout: score card + runs */}
      <div className="grid md:grid-cols-3 gap-6">
        <div className="md:col-span-1">
          <AgentScoreCard
            rank={profile.current_rank}
            breakdown={profile.score_breakdown}
          />
        </div>

        <div className="md:col-span-2 space-y-3">
          <h3 className="text-lg font-semibold">Recent Runs</h3>
          {profile.recent_runs.length === 0 ? (
            <div
              data-testid="empty-runs"
              className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 text-center"
            >
              <p className="text-zinc-400 text-sm">No runs yet.</p>
              <p className="text-zinc-500 text-xs mt-1">
                This agent hasn&apos;t competed in any benchmarks.
              </p>
            </div>
          ) : (
            profile.recent_runs.map((run) => (
              <RunSummaryCard key={run.run_id} run={run} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
