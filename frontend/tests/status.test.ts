import { describe, expect, it } from 'vitest';

import { isStatus, STATUSES, statusColors } from '@/design-system';

// The status vocabulary is the design ⟷ domain seam (§8). These tests pin the five
// canonical values and that every one resolves to token references (never raw hex),
// so the mapping inverts with the theme.
describe('status vocabulary (§8 alignment)', () => {
  it('exposes exactly the five canonical statuses', () => {
    expect([...STATUSES]).toEqual(['critical', 'high', 'medium', 'low', 'good']);
  });

  it('maps every status to text + tint token references', () => {
    for (const status of STATUSES) {
      const { text, tint } = statusColors(status);
      expect(text).toBe(`var(--ds-status-${status}-text)`);
      expect(tint).toBe(`var(--ds-status-${status}-tint)`);
    }
  });

  it('recognises known statuses and rejects unknown ones', () => {
    expect(isStatus('critical')).toBe(true);
    expect(isStatus('catastrophic')).toBe(false);
  });
});
