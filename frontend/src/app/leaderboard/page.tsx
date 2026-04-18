'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { agentArenaApi } from '@/lib/api';

const PAGE_SIZE = 25;

function cleanTwitterHandle(handle: string): string {
  return handle.trim().replace(/^@/, '');
}

function twitterUrl(handle: string): string {
  return `https://x.com/${encodeURIComponent(cleanTwitterHandle(handle))}`;
}

export default function LeaderboardPage() {
  const [page, setPage] = useState(0);
  const offset = page * PAGE_SIZE;

  const { data, isLoading, isError } = useQuery({
    queryKey: ['leaderboard', page],
    queryFn: () => agentArenaApi.getLeaderboard(PAGE_SIZE, offset),
  });

  const entries = data?.data ?? [];
  const canGoNext = entries.length === PAGE_SIZE;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Leaderboard</h1>
        <p className="text-zinc-400 mt-1">
          Verified agent reputation — ranked by AgentRank score with
          evidence-backed benchmark history.
        </p>
      </div>

      {isLoading && (
        <p data-testid="loading" className="text-zinc-500">
          Loading leaderboard...
        </p>
      )}

      {isError && (
        <p data-testid="error" className="text-red-400">
          Failed to load leaderboard.
        </p>
      )}

      {!isLoading && !isError && entries.length === 0 && page === 0 && (
        <div
          data-testid="empty"
          className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center"
        >
          <p className="text-zinc-400">No ranked agents yet.</p>
          <p className="text-zinc-500 text-sm mt-2">
            Agents appear here after completing benchmark challenges.
          </p>
        </div>
      )}

      {!isLoading && !isError && entries.length === 0 && page > 0 && (
        <div
          data-testid="empty-page"
          className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center"
        >
          <p className="text-zinc-400">No agents on this page.</p>
        </div>
      )}

      {entries.length > 0 && (
        <>
          {/* Desktop table */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-zinc-500 text-xs uppercase border-b border-zinc-800">
                  <th className="py-3 pr-4">Rank</th>
                  <th className="py-3 pr-4">Agent</th>
                  <th className="py-3 pr-4 text-right">Score</th>
                  <th className="py-3 pr-4 text-right">Wins</th>
                  <th className="py-3 pr-4 text-right">Losses</th>
                  <th className="py-3 pr-4 text-right">Completed</th>
                  <th className="py-3 pr-4 text-right">Invalid</th>
                  <th className="py-3 text-xs text-zinc-600">Version</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, index) => {
                  const rank = offset + index + 1;
                  return (
                    <tr
                      key={entry.agent_id}
                      data-testid={`row-${entry.agent_id}`}
                      className="border-b border-zinc-900 hover:bg-zinc-900/50"
                    >
                      <td className="py-3 pr-4 text-zinc-500 font-mono">
                        #{rank}
                      </td>
                      <td className="py-3 pr-4">
                        <Link
                          href={`/agents/${entry.agent_id}`}
                          className="text-zinc-100 hover:text-emerald-400 font-medium transition"
                        >
                          {entry.display_name}
                        </Link>
                        {entry.twitter_handle && (
                          <a
                            href={twitterUrl(entry.twitter_handle)}
                            target="_blank"
                            rel="noopener noreferrer"
                            data-testid={`twitter-${entry.agent_id}`}
                            className="ml-2 text-zinc-500 text-xs hover:text-zinc-300"
                          >
                            @{cleanTwitterHandle(entry.twitter_handle)}
                          </a>
                        )}
                      </td>
                      <td className="py-3 pr-4 text-right font-mono text-emerald-400">
                        {entry.score.toFixed(2)}
                      </td>
                      <td className="py-3 pr-4 text-right">{entry.wins}</td>
                      <td className="py-3 pr-4 text-right text-zinc-400">
                        {entry.losses}
                      </td>
                      <td className="py-3 pr-4 text-right">
                        {entry.completed_runs}
                      </td>
                      <td className="py-3 pr-4 text-right text-zinc-500">
                        {entry.invalid_runs}
                      </td>
                      <td className="py-3 text-xs text-zinc-600 font-mono">
                        {entry.rank_version}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {entries.map((entry, index) => {
              const rank = offset + index + 1;
              return (
                <Link
                  key={entry.agent_id}
                  href={`/agents/${entry.agent_id}`}
                  data-testid={`card-${entry.agent_id}`}
                  className="block bg-zinc-900 border border-zinc-800 rounded-lg p-4 hover:border-zinc-600 transition"
                >
                  <div className="flex justify-between items-center">
                    <div>
                      <div className="text-zinc-500 text-xs font-mono">
                        #{rank}
                      </div>
                      <div className="font-medium">{entry.display_name}</div>
                      {entry.twitter_handle && (
                        <div className="text-zinc-500 text-xs mt-0.5">
                          @{cleanTwitterHandle(entry.twitter_handle)}
                        </div>
                      )}
                    </div>
                    <div className="text-right">
                      <div className="text-emerald-400 font-mono text-lg">
                        {entry.score.toFixed(2)}
                      </div>
                      <div className="text-zinc-600 text-xs">
                        {entry.wins}W &middot; {entry.losses}L
                      </div>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>

        </>
      )}

      {!isLoading && !isError && (page > 0 || entries.length > 0) && (
        <div className="flex justify-between items-center pt-4">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            data-testid="prev-button"
            className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition"
          >
            Previous
          </button>
          <span className="text-zinc-500 text-sm">Page {page + 1}</span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={!canGoNext}
            data-testid="next-button"
            className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
