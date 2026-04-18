import Link from 'next/link';
import type { ChallengeSummary } from '@/lib/types';

const STATUS_STYLES: Record<string, { label: string; className: string }> = {
  pending: { label: 'Pending', className: 'bg-zinc-700 text-zinc-300' },
  active: { label: 'Active', className: 'bg-emerald-900 text-emerald-300' },
  settling: { label: 'Settling', className: 'bg-yellow-900 text-yellow-300' },
  completed: { label: 'Completed', className: 'bg-blue-900 text-blue-300' },
  cancelled: { label: 'Cancelled', className: 'bg-red-900 text-red-300' },
};

export function ChallengeCard({ challenge }: { challenge: ChallengeSummary }) {
  const status = STATUS_STYLES[challenge.status] ?? {
    label: challenge.status,
    className: 'bg-zinc-700 text-zinc-400',
  };

  return (
    <Link
      href={`/challenges/${challenge.challenge_id}`}
      className="block bg-zinc-900 border border-zinc-800 hover:border-zinc-600 rounded-xl p-5 transition"
    >
      <div className="flex justify-between items-start">
        <div>
          <h3 className="font-semibold">Challenge #{challenge.challenge_id}</h3>
          <p className="text-zinc-500 text-sm mt-1">
            {challenge.challenge_type} &middot; {challenge.challenge_version}
          </p>
        </div>
        <span
          data-testid="status-badge"
          className={`px-2 py-0.5 rounded text-xs font-medium ${status.className}`}
        >
          {status.label}
        </span>
      </div>
      <div className="mt-3 flex gap-4 text-sm text-zinc-400">
        <span>{challenge.num_contestants} contestants</span>
        <span>{challenge.num_finalized} finalized</span>
      </div>
    </Link>
  );
}
