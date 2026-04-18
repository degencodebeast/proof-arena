'use client';

import { useState } from 'react';
import { usePrivy } from '@privy-io/react-auth';
import { useMutation } from '@tanstack/react-query';
import { agentArenaApi } from '@/lib/api';
import type { StrategyResponse } from '@/lib/types';

export function SubmitForm() {
  const { authenticated, getAccessToken, login } = usePrivy();
  const [agentName, setAgentName] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [configJson, setConfigJson] = useState('{}');

  const mutation = useMutation<StrategyResponse, Error>({
    mutationFn: async () => {
      if (!agentName.trim()) throw new Error('Agent name is required.');
      if (agentName.length > 64)
        throw new Error('Agent name must be 64 characters or fewer.');
      if (!systemPrompt.trim()) throw new Error('System prompt is required.');

      let config: Record<string, unknown>;
      try {
        config = JSON.parse(configJson);
      } catch {
        throw new Error('Config must be valid JSON.');
      }

      const token = await getAccessToken();
      if (!token)
        throw new Error(
          'Authentication required. Please sign in and try again.'
        );

      try {
        const res = await agentArenaApi.submitStrategy(
          { agent_name: agentName.trim(), system_prompt: systemPrompt, config },
          token
        );
        return res.data;
      } catch (err: unknown) {
        const axiosErr = err as {
          response?: { status?: number; data?: { detail?: string } };
        };
        const status = axiosErr?.response?.status;
        const detail = axiosErr?.response?.data?.detail;
        // Only surface detail for 4xx client errors (validation, rate limit)
        if (status && status >= 400 && status < 500 && typeof detail === 'string') {
          throw new Error(detail);
        }
        throw new Error('Submission failed. Please try again.');
      }
    },
  });

  if (!authenticated) {
    return (
      <div
        data-testid="auth-prompt"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-4"
      >
        <p className="text-zinc-300">
          Connect your wallet or sign in to submit a strategy.
        </p>
        <button
          onClick={login}
          className="bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-2 rounded-lg font-medium transition"
        >
          Sign In
        </button>
      </div>
    );
  }

  return (
    <form
      aria-label="Submit strategy"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
      className="space-y-6"
    >
      <div>
        <label htmlFor="agentName" className="block text-sm font-medium text-zinc-300">
          Agent Name
        </label>
        <input
          id="agentName"
          type="text"
          value={agentName}
          onChange={(e) => setAgentName(e.target.value)}
          maxLength={64}
          className="mt-1 w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:outline-none focus:border-emerald-500"
        />
        <p className="mt-1 text-xs text-zinc-500">{agentName.length}/64</p>
      </div>

      <div>
        <label htmlFor="systemPrompt" className="block text-sm font-medium text-zinc-300">
          System Prompt
        </label>
        <textarea
          id="systemPrompt"
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          rows={8}
          className="mt-1 w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 font-mono text-sm focus:outline-none focus:border-emerald-500"
        />
      </div>

      <div>
        <label htmlFor="configJson" className="block text-sm font-medium text-zinc-300">
          Config (JSON)
        </label>
        <textarea
          id="configJson"
          value={configJson}
          onChange={(e) => setConfigJson(e.target.value)}
          rows={5}
          className="mt-1 w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 font-mono text-sm focus:outline-none focus:border-emerald-500"
        />
      </div>

      {mutation.error && (
        <div
          role="alert"
          className="p-3 bg-red-900/30 border border-red-800 rounded-lg text-red-300 text-sm"
        >
          {mutation.error.message}
        </div>
      )}

      <button
        type="submit"
        disabled={mutation.isPending}
        className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-700 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg font-medium transition"
      >
        {mutation.isPending ? 'Submitting...' : 'Submit Strategy'}
      </button>

      {mutation.isSuccess && mutation.data && (
        <div
          data-testid="success-message"
          className="p-4 bg-emerald-900/30 border border-emerald-800 rounded-lg space-y-2"
        >
          <p className="text-emerald-300 font-medium">Strategy registered!</p>
          <p className="text-zinc-400 text-sm">
            <span className="text-zinc-500">Display Name:</span>{' '}
            {mutation.data.display_name}
          </p>
          <p className="text-zinc-400 text-sm font-mono break-all">
            <span className="text-zinc-500">Submission Hash:</span>{' '}
            {mutation.data.submission_hash}
          </p>
        </div>
      )}
    </form>
  );
}
