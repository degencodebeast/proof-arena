/**
 * Task 6 / A-5 — tests for the V2 trust-label contract on the frontend.
 *
 * Validates:
 * - TRUST_LABELS has exactly the three contract keys with the expected copy
 * - getTrustLabelDisplay returns the expected string for each label
 * - isTrustLabel correctly narrows known strings and rejects unknown ones
 * - TrustLabel type is a literal union of exactly three values (compile-time)
 */

import { describe, it, expect } from 'vitest';
import {
  TRUST_LABELS,
  TrustLabel,
  getTrustLabelDisplay,
  isTrustLabel,
} from '@/lib/trustLabels';

describe('Task 6 / A-5: trust-label contract', () => {
  it('TRUST_LABELS has exactly the three V2 keys with expected display text', () => {
    expect(TRUST_LABELS).toEqual({
      benchmarked_canonical_template: 'Canonical Template',
      benchmark_compatible_customized_instance: 'Customized Instance',
      external_custom_runtime: 'External Runtime',
    });
    expect(Object.keys(TRUST_LABELS)).toHaveLength(3);
  });

  it('getTrustLabelDisplay returns the correct display string for each label', () => {
    expect(getTrustLabelDisplay('benchmarked_canonical_template')).toBe(
      'Canonical Template',
    );
    expect(
      getTrustLabelDisplay('benchmark_compatible_customized_instance'),
    ).toBe('Customized Instance');
    expect(getTrustLabelDisplay('external_custom_runtime')).toBe(
      'External Runtime',
    );
  });

  it('isTrustLabel accepts each of the three contract values', () => {
    expect(isTrustLabel('benchmarked_canonical_template')).toBe(true);
    expect(isTrustLabel('benchmark_compatible_customized_instance')).toBe(true);
    expect(isTrustLabel('external_custom_runtime')).toBe(true);
  });

  it('isTrustLabel rejects arbitrary strings', () => {
    expect(isTrustLabel('invalid_label')).toBe(false);
    expect(isTrustLabel('')).toBe(false);
    expect(isTrustLabel('canonical_template')).toBe(false);
    expect(isTrustLabel('customized_instance')).toBe(false);
    expect(isTrustLabel('Canonical Template')).toBe(false); // display name, not key
  });

  it('isTrustLabel rejects inherited prototype keys like "toString"', () => {
    // Regression: the naive `value in TRUST_LABELS` check returned true for
    // inherited Object.prototype keys. The type guard now uses hasOwnProperty
    // so these must be rejected.
    expect(isTrustLabel('toString')).toBe(false);
    expect(isTrustLabel('constructor')).toBe(false);
    expect(isTrustLabel('hasOwnProperty')).toBe(false);
    expect(isTrustLabel('valueOf')).toBe(false);
  });

  it('TrustLabel type is a union of exactly the three contract literals', () => {
    // Compile-time assertion via exhaustive switch: if any of the three is
    // missing or a fourth is added, TypeScript will either fail to compile
    // (missing case) or refuse the unreachable branch (extra case).
    const names: Record<TrustLabel, string> = {
      benchmarked_canonical_template: 'a',
      benchmark_compatible_customized_instance: 'b',
      external_custom_runtime: 'c',
    };
    expect(Object.keys(names)).toHaveLength(3);
  });
});
