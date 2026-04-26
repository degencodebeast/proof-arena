'use client';

/**
 * Task 22 — public template detail page.
 *
 * Read-only honest detail view against Task 4's
 * `GET /api/v1/templates/{template_key}` 10-field response. The page
 * makes the canonical template legible via its envelope, default
 * config, published behavior spec, and flagship lineage — NOT via
 * benchmark scores or inherited reputation.
 *
 * Hard invariants:
 * - Deploy CTA for deployable templates is a real
 *   `<Link href={/templates/${template_key}/deploy}>` (Task 23
 *   co-landed the deploy route). Signpost CTA stays
 *   `<button disabled>` — non-deployable templates have no deploy
 *   destination. Anchors under `/templates/` are allowed in exactly
 *   the 1-segment detail or 2-segment `/deploy` shapes; any other
 *   deeper subpath remains forbidden.
 * - Flagship section ALWAYS renders. When `flagship_trust_label`
 *   is a known V2 value, show display label + Link to `/flagship`.
 *   Otherwise show null-state copy with NO flagship link.
 * - Published behavior spec is framed as a canonical published
 *   specification — NOT "chain of thought" / reasoning theater.
 * - No benchmark scores / wins / losses on the template layer
 *   (service boundary: lineage only).
 *
 * See `.taskmaster/docs/task22-edge-case-spec.md`.
 */

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';

import { agentArenaApi } from '@/lib/api';
import type { TemplateDetailResponse } from '@/lib/types';
import {
  TRUST_LABELS,
  type TrustLabel,
  getTrustLabelDisplay,
} from '@/lib/trustLabels';

function statusFromError(err: unknown): number | null {
  if (typeof err !== 'object' || err === null || !('response' in err)) {
    return null;
  }
  const resp = (err as { response?: { status?: number } }).response;
  return typeof resp?.status === 'number' ? resp.status : null;
}

function isKnownTrustLabel(label: string): label is TrustLabel {
  return label in TRUST_LABELS;
}

function formatConfigValue(v: unknown): string {
  if (Array.isArray(v)) return v.map((x) => String(x)).join(', ');
  if (v === null || v === undefined) return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export default function TemplateDetailPage() {
  const params = useParams<{ template_key: string }>();
  const templateKey = params?.template_key ?? '';

  const { data, isLoading, isError, error } = useQuery<TemplateDetailResponse>({
    queryKey: ['template', templateKey],
    queryFn: async () => (await agentArenaApi.getTemplate(templateKey)).data,
    enabled: typeof templateKey === 'string' && templateKey.length > 0,
    retry: false,
  });

  if (isLoading) {
    return (
      <p data-testid="template-detail-loading" className="text-zinc-500">
        Loading template…
      </p>
    );
  }

  if (isError) {
    const status = statusFromError(error);
    if (status === 404) {
      return (
        <div
          data-testid="template-detail-not-found"
          className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-2"
        >
          <p className="text-zinc-300">Template not found.</p>
          <p className="text-zinc-500 text-sm">
            The template key in the URL does not match any published template.
          </p>
        </div>
      );
    }
    return (
      <p data-testid="template-detail-error" className="text-red-400">
        Failed to load template.
      </p>
    );
  }

  const template = data!;
  const deployable = template.is_deployable;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div data-testid="template-detail-header" className="space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-3xl font-bold font-mono">
            {template.template_key}
          </h1>
          <span
            data-testid="template-detail-badge"
            className={
              deployable
                ? 'inline-block px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-900/40 text-emerald-300 border border-emerald-800'
                : 'inline-block px-2 py-0.5 rounded-md text-xs font-medium bg-amber-900/30 text-amber-300 border border-amber-800'
            }
          >
            {deployable ? 'Deployable' : 'Not yet live'}
          </span>
          <span className="text-xs text-zinc-500 font-mono">
            version {template.template_version}
          </span>
        </div>
        <p className="text-zinc-300 max-w-3xl">{template.description || '—'}</p>
      </div>

      {/* Flagship lineage — ALWAYS rendered */}
      <FlagshipSection trustLabel={template.flagship_trust_label} />

      {/* Customization envelope */}
      <section
        data-testid="envelope-section"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-5"
      >
        <h2 className="text-lg font-semibold mb-1">Customization envelope</h2>
        <p className="text-sm text-zinc-400 mb-3">
          Deployment exposes these{' '}
          <span className="text-zinc-300">{template.allowed_fields.length}</span>{' '}
          fields for customization. Values outside the envelope are rejected at
          deploy time.
        </p>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
          {template.allowed_fields.map((field) => (
            <li
              key={field}
              className="font-mono text-zinc-200 bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5"
            >
              {field}
            </li>
          ))}
        </ul>
      </section>

      {/* Default configuration */}
      <section
        data-testid="default-config-section"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-5"
      >
        <h2 className="text-lg font-semibold mb-1">Default configuration</h2>
        <p className="text-sm text-zinc-400 mb-3">
          Default values applied at deploy time. Override any of these within
          the envelope.
        </p>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          {Object.entries(template.default_config).map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="text-zinc-500 font-mono text-xs">{key}</dt>
              <dd className="text-zinc-200 font-mono break-words">
                {formatConfigValue(value)}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      {/* Behavior spec — canonical published specification */}
      <section
        data-testid="behavior-spec-section"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-5"
      >
        <h2 className="text-lg font-semibold mb-1">Published behavior spec</h2>
        <p className="text-sm text-zinc-400 mb-3">
          Canonical specification that governs how deployed instances of this
          template behave. Instances inherit this spec verbatim.
        </p>
        <pre className="bg-zinc-950 border border-zinc-800 rounded-md p-4 text-sm text-zinc-300 whitespace-pre-wrap font-mono">
          {template.system_prompt}
        </pre>
      </section>

      {/* Deploy CTA — real link for deployable (Task 23 co-landed), disabled for signposts */}
      <div className="flex items-center justify-end">
        {deployable ? (
          <Link
            href={`/templates/${template.template_key}/deploy`}
            data-testid="deploy-cta"
            className="inline-block px-4 py-2 rounded-md text-sm font-medium bg-emerald-700 hover:bg-emerald-600 text-white"
          >
            Deploy →
          </Link>
        ) : (
          <button
            type="button"
            disabled
            data-testid="deploy-cta"
            className="inline-block px-4 py-2 rounded-md text-sm font-medium bg-zinc-800 text-zinc-500 border border-zinc-700 cursor-not-allowed"
          >
            Coming Soon
          </button>
        )}
      </div>
    </div>
  );
}

function FlagshipSection({ trustLabel }: { trustLabel: string | null }) {
  const knownLive =
    trustLabel !== null &&
    isKnownTrustLabel(trustLabel) &&
    trustLabel === 'benchmarked_canonical_template';

  if (!knownLive) {
    // Null state OR defense-in-depth fallback for any unexpected
    // label value (e.g. the reserved `external_custom_runtime` that
    // no V2 code path currently assigns, or
    // `benchmark_compatible_customized_instance` which is NOT a
    // flagship promotion). Render honest null-state copy with no
    // `/flagship` link.
    return (
      <section
        data-testid="flagship-section"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-5"
      >
        <h2 className="text-xs uppercase tracking-wide text-zinc-500 mb-2">
          Flagship lineage
        </h2>
        <p className="text-sm text-zinc-300">
          No live flagship instance yet. The canonical flagship will be
          deployed by the platform bootstrap (Task 18).
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid="flagship-section"
      className="bg-emerald-950/20 border border-emerald-900/60 rounded-xl p-5"
    >
      <h2 className="text-xs uppercase tracking-wide text-emerald-400 mb-2">
        Flagship lineage
      </h2>
      <p className="text-sm text-zinc-200 mb-3">
        Flagship live:{' '}
        <span className="inline-block px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-900/40 text-emerald-300 border border-emerald-800 font-mono">
          {getTrustLabelDisplay(trustLabel as TrustLabel)}
        </span>{' '}
        — the canonical instance is deployed and benchmarked on Solana devnet.
      </p>
      <Link
        href="/flagship"
        className="inline-block text-sm text-emerald-300 hover:text-emerald-200 underline underline-offset-2"
      >
        View flagship →
      </Link>
    </section>
  );
}
