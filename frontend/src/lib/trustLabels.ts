/**
 * V2 trust-label contract — single source of truth for the three trust-label
 * display strings rendered across flagship, template detail, and instance
 * dashboard surfaces.
 *
 * Keys are byte-equal to the backend ``TrustLabel`` enum values in
 * ``backend/src/integrity/trust_labels.py`` and the DB CHECK constraint on
 * ``agent_instances.trust_label``.
 *
 * Semantics:
 * - ``benchmarked_canonical_template``: carried on the flagship hosted
 *   instance.
 * - ``benchmark_compatible_customized_instance``: user-deployed hosted
 *   instance that completed the deploy saga.
 * - ``external_custom_runtime``: **reserved** in V2. No V2 code path
 *   assigns it; the value exists so UI renders consistently when the
 *   post-V2 external-runtime path ships.
 */

export const TRUST_LABELS = {
  benchmarked_canonical_template: 'Canonical Template',
  benchmark_compatible_customized_instance: 'Customized Instance',
  external_custom_runtime: 'External Runtime',
} as const;

/** Union of the three valid V2 trust-label string literals. */
export type TrustLabel = keyof typeof TRUST_LABELS;

/** Display name for a known trust label. */
export function getTrustLabelDisplay(label: TrustLabel): string {
  return TRUST_LABELS[label];
}

/** Type guard: narrow an arbitrary string to a known trust label.
 *
 * Uses ``Object.prototype.hasOwnProperty`` so inherited prototype keys like
 * ``toString`` / ``constructor`` are not mis-classified as valid labels.
 */
export function isTrustLabel(value: string): value is TrustLabel {
  return Object.prototype.hasOwnProperty.call(TRUST_LABELS, value);
}
