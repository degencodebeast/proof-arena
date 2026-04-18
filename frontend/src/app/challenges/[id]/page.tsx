'use client';

import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { agentArenaApi } from '@/lib/api';
import { LiveRunView } from '@/components/challenge/LiveRunView';
import { ContestantsList } from '@/components/challenge/ContestantsList';

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-zinc-700 text-zinc-300',
  active: 'bg-emerald-900 text-emerald-300',
  settling: 'bg-yellow-900 text-yellow-300',
  completed: 'bg-blue-900 text-blue-300',
};

export default function ChallengeDetailPage() {
  const params = useParams();
  const rawId = params?.id;
  // Strict positive integer match — rejects "1abc", "1.5", "-1", "0", leading zeros
  const isValidId = typeof rawId === 'string' && /^[1-9]\d*$/.test(rawId);
  const challengeId = isValidId ? Number(rawId) : NaN;

  const isTerminal = (s?: string) =>
    s === 'completed' || s === 'cancelled';

  const {
    data: challengeRes,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['challenge', challengeId],
    queryFn: () => agentArenaApi.getChallenge(challengeId),
    enabled: isValidId,
    refetchInterval: (query) => {
      if (query.state.status === 'error') return false;
      const status = query.state.data?.data?.status;
      if (!status || isTerminal(status)) return false;
      return 10000;
    },
  });

  const challenge = challengeRes?.data;
  const isActive = challenge?.status === 'active';

  const { data: eventsRes, isError: isEventsError, isLoading: isEventsLoading } = useQuery({
    queryKey: ['challenge-events', challengeId],
    queryFn: () => agentArenaApi.getChallengeEvents(challengeId),
    refetchInterval: isActive ? 5000 : false,
    enabled: isValidId && !!challenge,
  });

  if (!isValidId) {
    return (
      <div className="space-y-6">
        <p data-testid="invalid-id" className="text-red-400">
          Invalid challenge ID.
        </p>
        <Link
          href="/challenges"
          className="text-emerald-400 hover:underline text-sm"
        >
          Back to challenges
        </Link>
      </div>
    );
  }

  if (isLoading) {
    return (
      <p data-testid="loading" className="text-zinc-500">
        Loading challenge...
      </p>
    );
  }

  if (isError || !challenge) {
    return (
      <p data-testid="error" className="text-red-400">
        Failed to load challenge.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-start">
        <div>
          <Link
            href="/challenges"
            className="text-emerald-400 hover:underline text-sm"
          >
            &larr; Back to challenges
          </Link>
          <h1 className="text-3xl font-bold mt-2">
            Challenge #{challenge.challenge_id}
          </h1>
          <p className="text-zinc-500 text-sm mt-1">
            {challenge.challenge_type} &middot; {challenge.challenge_version}
          </p>
        </div>
        <span
          data-testid="detail-status-badge"
          className={`px-3 py-1 rounded text-sm font-medium ${
            STATUS_STYLES[challenge.status] ?? 'bg-zinc-700 text-zinc-400'
          }`}
        >
          {challenge.status}
        </span>
      </div>

      <div className="grid md:grid-cols-3 gap-4 text-sm">
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <span className="text-zinc-500">Model</span>
          <p className="text-zinc-200 mt-1">
            {challenge.llm_provider} / {challenge.llm_model}
          </p>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <span className="text-zinc-500">Contestants</span>
          <p className="text-zinc-200 mt-1">
            {challenge.num_finalized} / {challenge.num_contestants} finalized
          </p>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <span className="text-zinc-500">Created</span>
          <p className="text-zinc-200 mt-1">
            {new Date(challenge.created_at).toLocaleDateString()}
          </p>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        <div className="md:col-span-2">
          <LiveRunView events={eventsRes?.data} isError={isEventsError} isLoading={isEventsLoading} />
        </div>
        <div>
          <ContestantsList
            contestants={challenge.contestants}
            winnerAgentId={challenge.winner_agent_id}
          />
        </div>
      </div>
    </div>
  );
}
