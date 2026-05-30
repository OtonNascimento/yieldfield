// Loading this module registers the token custom properties (§5A). Every other
// layer references tokens through `cssVar` or `var(--…)`, never raw hex.
import './tokens.css';

/** Reference a design-system CSS custom property as a CSS value string. */
export const cssVar = (name: string): string => `var(--${name})`;
