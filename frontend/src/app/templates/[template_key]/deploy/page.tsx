'use client';

/**
 * Task 23 — deploy flow page.
 *
 * Loads the Task 4 template detail, prepopulates the V2 5-field
 * envelope form from `default_config`, collects the 4 required
 * consent acknowledgments, and POSTs to
 * `/api/v1/instances/deploy` (Task 23 backend adapter). On 200
 * with `status === 'live'`, navigates to `/instances/{id}`. On
 * partial-saga (`*_failed` status), surfaces the failure reason
 * and still offers a View-instance link (operator can repair via
 * Task 14). All consent copy is devnet-only and platform-managed
 * signing — never custody framing, never mainnet implication.
 *
 * See `.taskmaster/docs/task23-edge-case-spec.md`.
 */

import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { usePrivy } from '@privy-io/react-auth';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';

import { agentArenaApi } from '@/lib/api';
import type {
  InstanceDeployRequest,
  InstanceDeployResponse,
  TemplateDetailResponse,
} from '@/lib/types';

type ConsentKey =
  | 'devnet_only_acknowledged'
  | 'platform_managed_signing_acknowledged'
  | 'spend_caps_acknowledged'
  | 'no_indemnity_acknowledged';

const CONSENT_LABELS: Record<ConsentKey, string> = {
  devnet_only_acknowledged:
    'I understand this deploys a benchmark instance on Solana devnet. Never on mainnet.',
  platform_managed_signing_acknowledged:
    "I understand Proof Arena does not hold the raw key. Proof Arena holds an authorization key that causes Privy's enclave to sign transactions within an allowlisted program policy.",
  spend_caps_acknowledged:
    'I understand spend is bounded by the envelope (max_position_size, max_slippage_bps) and by the wallet policy allowlist.',
  no_indemnity_acknowledged:
    'I understand benchmark runs are experimental and Proof Arena provides no indemnity for outcomes.',
};

const CONSENT_KEYS = Object.keys(CONSENT_LABELS) as ConsentKey[];

const ENVELOPE_NUMERIC_FIELDS = [
  'max_slippage_bps',
  'max_position_size',
  'max_iterations',
  'max_runtime_seconds',
] as const;

function statusFromError(err: unknown): number | null {
  if (typeof err !== 'object' || err === null || !('response' in err)) return null;
  const resp = (err as { response?: { status?: number } }).response;
  return typeof resp?.status === 'number' ? resp.status : null;
}

function detailFromError(err: unknown): string | null {
  if (typeof err !== 'object' || err === null || !('response' in err)) return null;
  const resp = (err as { response?: { data?: { detail?: string } } }).response;
  return resp?.data?.detail ?? null;
}

export default function TemplateDeployPage() {
  const params = useParams<{ template_key: string }>();
  const templateKey = params?.template_key ?? '';
  const { authenticated, login } = usePrivy();

  const {
    data: template,
    isLoading: templateLoading,
    isError: templateIsError,
    error: templateError,
  } = useQuery<TemplateDetailResponse>({
    queryKey: ['template', templateKey],
    queryFn: async () => (await agentArenaApi.getTemplate(templateKey)).data,
    enabled:
      authenticated && typeof templateKey === 'string' && templateKey.length > 0,
    retry: false,
  });

  if (!authenticated) {
    return (
      <div
        data-testid="auth-prompt"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-4"
      >
        <p className="text-zinc-300">Sign in to deploy a hosted instance.</p>
        <button
          onClick={() => login()}
          className="inline-block px-4 py-2 rounded-md bg-emerald-700 hover:bg-emerald-600 text-white text-sm font-medium"
        >
          Sign in
        </button>
      </div>
    );
  }

  if (templateLoading) {
    return (
      <p data-testid="template-loading" className="text-zinc-500">
        Loading template…
      </p>
    );
  }

  if (templateIsError) {
    const status = statusFromError(templateError);
    if (status === 404) {
      return (
        <div
          data-testid="template-not-found"
          className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center"
        >
          <p className="text-zinc-300">Template not found.</p>
        </div>
      );
    }
    return (
      <p data-testid="template-error" className="text-red-400">
        Failed to load template.
      </p>
    );
  }

  if (!template) {
    // Should never happen (isLoading/isError cover this) but keep a
    // safe fallback that renders the loading state.
    return (
      <p data-testid="template-loading" className="text-zinc-500">
        Loading template…
      </p>
    );
  }

  if (!template.is_deployable) {
    return (
      <div
        data-testid="template-not-deployable"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-2"
      >
        <p className="text-zinc-300">This template is not yet live.</p>
        <p className="text-zinc-500 text-sm">
          Signpost templates preview follow-on families. Deployment is not
          available yet.
        </p>
        <Link
          href={`/templates/${templateKey}`}
          className="inline-block text-sm text-emerald-300 hover:text-emerald-200 underline underline-offset-2"
        >
          ← Back to template
        </Link>
      </div>
    );
  }

  return <DeployForm template={template} templateKey={templateKey} />;
}

function DeployForm({
  template,
  templateKey,
}: {
  template: TemplateDetailResponse;
  templateKey: string;
}) {
  const { getAccessToken } = usePrivy();
  const router = useRouter();

  const defaultAllowedTokens: string[] = (() => {
    const raw = (template.default_config as Record<string, unknown>)
      .allowed_token_universe;
    return Array.isArray(raw) ? raw.map((v) => String(v)) : [];
  })();

  const [tokens, setTokens] = useState<string>(defaultAllowedTokens.join(', '));
  const [numericFields, setNumericFields] = useState<Record<string, string>>(
    () => {
      const initial: Record<string, string> = {};
      for (const k of ENVELOPE_NUMERIC_FIELDS) {
        const v = (template.default_config as Record<string, unknown>)[k];
        initial[k] = v !== undefined ? String(v) : '';
      }
      return initial;
    },
  );
  const [consentState, setConsentState] = useState<Record<ConsentKey, boolean>>({
    devnet_only_acknowledged: false,
    platform_managed_signing_acknowledged: false,
    spend_caps_acknowledged: false,
    no_indemnity_acknowledged: false,
  });

  const allConsentChecked = CONSENT_KEYS.every((k) => consentState[k]);
  const numericValid = ENVELOPE_NUMERIC_FIELDS.every((k) => {
    const v = numericFields[k];
    return v !== undefined && v.trim().length > 0 && !Number.isNaN(Number(v));
  });
  const tokensValid =
    tokens
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean).length > 0;

  const mutation = useMutation<
    InstanceDeployResponse,
    unknown,
    InstanceDeployRequest
  >({
    mutationFn: async (body) => {
      const token = await getAccessToken();
      if (!token) throw new Error('auth-missing');
      const res = await agentArenaApi.deployInstance(body, token);
      return res.data;
    },
    onSuccess: (data) => {
      if (data.status === 'live') {
        router.push(`/instances/${data.instance_id}`);
      }
      // For *_failed states we stay on the page and render the
      // failure reason; user can click View instance to inspect.
    },
    retry: false,
  });

  const canSubmit =
    numericValid && tokensValid && allConsentChecked && !mutation.isPending;
  const result = mutation.data;
  const resultIsPartialSaga = !!result && result.status !== 'live';

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    const effective_config: Record<string, unknown> = {
      allowed_token_universe: tokens
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    };
    for (const k of ENVELOPE_NUMERIC_FIELDS) {
      effective_config[k] = Number(numericFields[k]);
    }
    mutation.mutate({
      template_key: templateKey,
      effective_config,
      consent: { ...consentState },
    });
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-3xl font-bold">Deploy instance</h1>
        <p className="text-zinc-400 mt-2">
          Deploying a customized instance of{' '}
          <span className="font-mono text-zinc-200">{templateKey}</span> on
          Solana devnet.
        </p>
      </div>

      <form
        data-testid="deploy-form"
        onSubmit={handleSubmit}
        className="space-y-6"
      >
        {/* Envelope fields */}
        <section className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
          <h2 className="text-lg font-semibold">Configuration</h2>
          <p className="text-sm text-zinc-400">
            Customize the 5-field envelope. Values outside the envelope are
            rejected at deploy time.
          </p>
          <label className="block space-y-1">
            <span className="text-xs font-mono text-zinc-400">
              allowed_token_universe
            </span>
            <input
              data-testid="field-allowed-token-universe"
              type="text"
              value={tokens}
              onChange={(e) => setTokens(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono text-zinc-200"
              placeholder="comma,separated,mints"
            />
          </label>
          {ENVELOPE_NUMERIC_FIELDS.map((k) => (
            <label key={k} className="block space-y-1">
              <span className="text-xs font-mono text-zinc-400">{k}</span>
              <input
                data-testid={`field-${k}`}
                type="number"
                value={numericFields[k]}
                onChange={(e) =>
                  setNumericFields((prev) => ({ ...prev, [k]: e.target.value }))
                }
                className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm font-mono text-zinc-200"
              />
            </label>
          ))}
        </section>

        {/* Consent */}
        <section
          data-testid="consent-section"
          className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3"
        >
          <h2 className="text-lg font-semibold">Consent</h2>
          {CONSENT_KEYS.map((k) => (
            <label
              key={k}
              className="flex items-start gap-3 text-sm text-zinc-300"
            >
              <input
                type="checkbox"
                data-testid={`consent-${k}`}
                checked={consentState[k]}
                onChange={(e) =>
                  setConsentState((prev) => ({ ...prev, [k]: e.target.checked }))
                }
                className="mt-1 shrink-0"
              />
              <span>{CONSENT_LABELS[k]}</span>
            </label>
          ))}
        </section>

        {/* Submit + result */}
        <div className="flex items-center gap-4">
          <button
            type="submit"
            disabled={!canSubmit}
            data-testid="deploy-submit"
            className={
              canSubmit
                ? 'inline-block px-4 py-2 rounded-md bg-emerald-700 hover:bg-emerald-600 text-white text-sm font-medium'
                : 'inline-block px-4 py-2 rounded-md bg-zinc-800 text-zinc-500 border border-zinc-700 cursor-not-allowed text-sm font-medium'
            }
          >
            {mutation.isPending ? 'Deploying…' : 'Deploy →'}
          </button>
          {mutation.isError ? (
            <span data-testid="deploy-error" className="text-red-400 text-sm">
              {statusFromError(mutation.error) === 503
                ? 'Deploy stack is temporarily unavailable. Retry soon.'
                : detailFromError(mutation.error) ?? 'Deploy failed.'}
            </span>
          ) : null}
        </div>

        {resultIsPartialSaga && result ? (
          <div
            data-testid="deploy-partial-saga"
            className="bg-amber-950/30 border border-amber-900 rounded-xl p-4 text-amber-200 text-sm space-y-2"
          >
            <p>
              Deploy completed with partial-saga status{' '}
              <span className="font-mono">{result.status}</span>. Reason:{' '}
              <span className="font-mono">{result.last_failure_reason}</span>.
            </p>
            <Link
              href={`/instances/${result.instance_id}`}
              className="inline-block text-amber-300 hover:text-amber-200 underline underline-offset-2"
            >
              View instance →
            </Link>
          </div>
        ) : null}
      </form>
    </div>
  );
}
