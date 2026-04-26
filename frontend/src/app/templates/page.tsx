'use client';

/**
 * Task 21 — public template catalog page.
 *
 * Read-only honest catalog against Task 4's `GET /api/v1/templates`
 * 5-field summary shape. Post Task 22 + Task 23 co-land, the card
 * title wraps in `<Link href={/templates/${template_key}}>` pointing
 * at the shipped detail page, and the deployable CTA wraps in
 * `<Link href={/templates/${template_key}/deploy}>` pointing at the
 * shipped Task 23 deploy route. Anchors under `/templates/` are
 * allowed in exactly two shapes: 1-segment detail and 2-segment
 * `/deploy`; any other deeper subpath remains forbidden. Signpost
 * templates (is_deployable=false) keep their distinct "Not yet live"
 * badge + "Coming Soon" `<button disabled>` CTA.
 *
 * See `.taskmaster/docs/task21-edge-case-spec.md` for the T1-T11
 * edge-case map.
 */

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { agentArenaApi } from '@/lib/api';
import type { TemplateSummary } from '@/lib/types';

function formatCreatedAt(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace('T', ' ').slice(0, 10);
}

export default function TemplatesCatalogPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['templates'],
    queryFn: async () => (await agentArenaApi.listTemplates()).data,
    retry: false,
  });

  if (isLoading) {
    return (
      <p data-testid="templates-loading" className="text-zinc-500">
        Loading templates…
      </p>
    );
  }

  if (isError) {
    return (
      <div
        data-testid="templates-error"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-2"
      >
        <p className="text-red-400">Failed to load templates.</p>
        <p className="text-zinc-500 text-sm">
          Please refresh the page to try again.
        </p>
      </div>
    );
  }

  const templates: TemplateSummary[] = data ?? [];

  if (templates.length === 0) {
    return (
      <div
        data-testid="templates-empty"
        className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center space-y-2"
      >
        <p className="text-zinc-300">No templates published yet.</p>
        <p className="text-zinc-500 text-sm">
          Once a template is registered, it will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold">Templates</h2>
        <p className="text-zinc-400 mt-2 max-w-2xl">
          Canonical agent templates on Solana devnet. Deployable templates
          can be customized into your own private hosted instance. Signpost
          templates are follow-on families not yet live — they preview
          where the platform is heading.
        </p>
      </div>

      <ul
        data-testid="template-list"
        className="grid grid-cols-1 md:grid-cols-2 gap-4"
      >
        {templates.map((t) => (
          <TemplateCard key={t.template_key} template={t} />
        ))}
      </ul>
    </div>
  );
}

function TemplateCard({ template }: { template: TemplateSummary }) {
  const deployable = template.is_deployable;
  const testId = `template-card-${template.template_key}`;
  const accentClass = deployable
    ? 'border-emerald-900/60 bg-gradient-to-b from-emerald-950/20 to-zinc-900'
    : 'border-zinc-800 bg-zinc-900';

  return (
    <li
      data-testid={testId}
      className={`rounded-xl border ${accentClass} p-5 flex flex-col gap-4`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {/*
            Task 22 landed `/templates/[template_key]` — the card title
            links to the real detail route. Task 23 landed
            `/templates/{key}/deploy`, so the deployable CTA below is
            also a real <Link>; signpost CTA stays disabled.
          */}
          <Link
            href={`/templates/${template.template_key}`}
            className="inline-block hover:underline underline-offset-2"
          >
            <h3
              data-testid={`${testId}-title`}
              className="text-lg font-semibold font-mono text-zinc-100 break-words"
            >
              {template.template_key}
            </h3>
          </Link>
          <p className="text-xs text-zinc-500 font-mono mt-1">
            {template.template_version}
          </p>
        </div>
        <span
          data-testid={`${testId}-badge`}
          className={
            deployable
              ? 'shrink-0 inline-block px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-900/40 text-emerald-300 border border-emerald-800'
              : 'shrink-0 inline-block px-2 py-0.5 rounded-md text-xs font-medium bg-amber-900/30 text-amber-300 border border-amber-800'
          }
        >
          {deployable ? 'Deployable' : 'Not yet live'}
        </span>
      </div>

      <p className="text-sm text-zinc-300 leading-relaxed">
        {template.description || '—'}
      </p>

      <div className="flex items-center justify-between text-xs text-zinc-500 mt-auto pt-2">
        <span>Registered {formatCreatedAt(template.created_at)}</span>
        {deployable ? (
          <Link
            href={`/templates/${template.template_key}/deploy`}
            data-testid={`${testId}-cta`}
            className="inline-block px-3 py-1.5 rounded-md text-xs font-medium bg-emerald-700 hover:bg-emerald-600 text-white"
          >
            Deploy →
          </Link>
        ) : (
          <button
            type="button"
            disabled
            data-testid={`${testId}-cta`}
            className="inline-block px-3 py-1.5 rounded-md text-xs font-medium bg-zinc-800 text-zinc-500 border border-zinc-700 cursor-not-allowed"
          >
            Coming Soon
          </button>
        )}
      </div>
    </li>
  );
}
