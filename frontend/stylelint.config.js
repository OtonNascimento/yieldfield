/**
 * Stylelint enforces the CSS half of the design-system boundary (§5A):
 * no hard-coded hex colors anywhere except the tokens layer, which is the single
 * authoritative source of color values. The delivered reference CSS is preserved
 * verbatim and excluded.
 */
export default {
  extends: ['stylelint-config-standard'],
  ignoreFiles: ['src/design-system/reference/**', 'dist/**', 'node_modules/**'],
  rules: {
    'color-no-hex': true,
    // Allow the design-system token namespace (`--ds-*`, `--brand`, etc.).
    'custom-property-pattern': null,
    // Token files are long sequential lists of custom properties; do not demand
    // a blank line between each one.
    'custom-property-empty-line-before': null,
  },
  overrides: [
    {
      // Tokens are the ONE place raw hex is permitted — they define the palette
      // every other layer references via var() (§5A).
      files: ['src/design-system/tokens/**/*.css'],
      rules: {
        'color-no-hex': null,
      },
    },
  ],
};
