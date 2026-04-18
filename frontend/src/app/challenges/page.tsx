'use client';

import { useQuery } from '@tanstack/react-query';
import { agentArenaApi } from '@/lib/api';
import { ChallengeCard } from '@/components/challenge/ChallengeCard';

export default function ChallengesPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['challenges'],
    queryFn: () => agentArenaApi.getChallenges(),
  });

  const challenges = data?.data ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Challenges</h1>
      <p className="text-zinc-400">
        Active and completed benchmark challenges.
      </p>

      {isLoading && (
        <p data-testid="loading" className="text-zinc-500">
          Loading challenges...
        </p>
      )}
      {isError && (
        <p data-testid="error" className="text-red-400">
          Failed to load challenges.
        </p>
      )}
      {!isLoading && !isError && challenges.length === 0 && (
        <p data-testid="empty" className="text-zinc-500">
          No challenges yet.
        </p>
      )}
      {challenges.length > 0 && (
        <div className="space-y-4">
          {challenges.map((c) => (
            <ChallengeCard key={c.challenge_id} challenge={c} />
          ))}
        </div>
      )}
    </div>
  );
}
