'use client';

import { useState } from 'react';
import { usePrivy } from '@privy-io/react-auth';
import { useMutation } from '@tanstack/react-query';
import { agentArenaApi } from '@/lib/api';
import type { StrategyResponse } from '@/lib/types';

export const STRATEGY_TEMPLATES = {
  CONSERVATIVE: {
    label: 'Conservative',
    description:
      'Prioritizes capital preservation, low slippage, and stable routes.',
    system_prompt:
      'Execute swaps conservatively with low slippage. Prefer stable routes. Minimize unnecessary swaps. Prioritize capital preservation while completing the required basket.',
    config: {
      risk_level: 'low',
      max_slippage_bps: 50,
      prefer_stable_routes: true,
      swap_frequency: 'low',
    },
  },
  BALANCED: {
    label: 'Balanced',
    description: 'Balances completion, execution quality, and opportunity.',
    system_prompt:
      'Balance risk and opportunity. Use moderate slippage tolerance. Complete the required basket while avoiding unnecessary invalid actions or excessive waiting.',
    config: {
      risk_level: 'medium',
      max_slippage_bps: 100,
      prefer_stable_routes: null,
      swap_frequency: 'medium',
    },
  },
  AGGRESSIVE: {
    label: 'Aggressive',
    description:
      'Optimizes for ending value while staying inside benchmark rules.',
    system_prompt:
      'Maximize ending value while staying inside the challenge rules. Accept higher allowed slippage when justified by available quotes. Complete required swaps efficiently.',
    config: {
      risk_level: 'high',
      max_slippage_bps: 200,
      prefer_stable_routes: false,
      swap_frequency: 'high',
    },
  },
} as const;

export type TemplateKey = keyof typeof STRATEGY_TEMPLATES;
const TEMPLATE_KEYS = Object.keys(STRATEGY_TEMPLATES) as TemplateKey[];

export function StrategyBuilderLite() {
  const { authenticated, getAccessToken, login } = usePrivy();
  const [selected, setSelected] = useState<TemplateKey | null>(null);
  const [agentName, setAgentName] = useState('');

  const template = selected ? STRATEGY_TEMPLATES[selected] : null;

  const mutation = useMutation<StrategyResponse, Error>({
    mutationFn: async () => {
      if (!template) throw new Error('Please select a strategy template.');
      if (!agentName.trim()) throw new Error('Agent name is required.');
      if (agentName.length > 64)
        throw new Error('Agent name must be 64 characters or fewer.');

      const token = await getAccessToken();
      if (!token)
        throw new Error(
          'Authentication required. Please sign in and try again.'
        );

      try {
        const res = await agentArenaApi.submitStrategy(
          {
            agent_name: agentName.trim(),
            system_prompt: template.system_prompt,
            config: { ...template.config },
          },
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
          Connect your wallet or sign in to use the Strategy Builder.
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
    <div className="space-y-6">
      <div className="grid md:grid-cols-3 gap-4">
        {TEMPLATE_KEYS.map((key) => {
          const t = STRATEGY_TEMPLATES[key];
          const isSelected = selected === key;
          return (
            <button
              key={key}
              onClick={() => setSelected(key)}
              data-testid={`template-${key}`}
              className={`text-left p-5 rounded-xl border transition ${
                isSelected
                  ? 'border-emerald-500 bg-emerald-900/20'
                  : 'border-zinc-800 bg-zinc-900 hover:border-zinc-600'
              }`}
            >
              <h3 className="font-semibold text-emerald-400">{t.label}</h3>
              <p className="text-zinc-500 text-sm mt-2">{t.description}</p>
            </button>
          );
        })}
      </div>

      {template && (
        <div className="space-y-4">
          <div>
            <label
              htmlFor="builderAgentName"
              className="block text-sm font-medium text-zinc-300"
            >
              Agent Name
            </label>
            <input
              id="builderAgentName"
              type="text"
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              maxLength={64}
              placeholder="Enter a name for your agent"
              className="mt-1 w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:outline-none focus:border-emerald-500"
            />
            <p className="mt-1 text-xs text-zinc-500">{agentName.length}/64</p>
          </div>

          <div data-testid="template-preview">
            <h4 className="text-sm font-medium text-zinc-300 mb-2">Preview</h4>
            <div className="bg-zinc-800 rounded-lg p-4 space-y-3">
              <div>
                <span className="text-xs text-zinc-500">System Prompt</span>
                <p className="text-sm text-zinc-300 font-mono mt-1">
                  {template.system_prompt}
                </p>
              </div>
              <div>
                <span className="text-xs text-zinc-500">Config</span>
                <pre className="text-sm text-zinc-300 font-mono mt-1">
                  {JSON.stringify(template.config, null, 2)}
                </pre>
              </div>
            </div>
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
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            data-testid="builder-submit"
            className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-700 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg font-medium transition"
          >
            {mutation.isPending ? 'Submitting...' : 'Submit Strategy'}
          </button>

          {mutation.isSuccess && mutation.data && (
            <div
              data-testid="success-message"
              className="p-4 bg-emerald-900/30 border border-emerald-800 rounded-lg space-y-2"
            >
              <p className="text-emerald-300 font-medium">
                Strategy registered!
              </p>
              <p className="text-zinc-400 text-sm font-mono break-all">
                <span className="text-zinc-500">Submission Hash:</span>{' '}
                {mutation.data.submission_hash}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
