/**
 * The status vocabulary — the single design ⟷ domain mapping (§8, §5A).
 *
 * These five values ARE the canonical domain severity/status tokens. The backend
 * emits exactly these strings (Slice 1 domain enum), and this module is the one
 * place they map to color tokens — no per-component translation table. Because the
 * values are token references, they invert automatically with the theme.
 */

export const STATUSES = ['critical', 'high', 'medium', 'low', 'good'] as const;

export type Status = (typeof STATUSES)[number];

export interface StatusColors {
  /** Foreground text color token for this status. */
  readonly text: string;
  /** Background tint color token for this status. */
  readonly tint: string;
}

/** Map a domain status to its design-system color tokens. */
export function statusColors(status: Status): StatusColors {
  return {
    text: `var(--ds-status-${status}-text)`,
    tint: `var(--ds-status-${status}-tint)`,
  };
}

/** Type guard: is an arbitrary backend string a known status? */
export function isStatus(value: string): value is Status {
  return (STATUSES as readonly string[]).includes(value);
}
