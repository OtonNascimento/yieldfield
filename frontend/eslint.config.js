import js from '@eslint/js';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

// The frontend half of Slice 0's mandated import-boundary lint (§5A, §6.3).
// Two invariants are enforced here as ESLint rules; CSS hex is enforced by
// Stylelint (see stylelint.config.js):
//   1. No hard-coded hex color literals outside the design-system layer.
//   2. The layer dependency direction: features -> design-system/shared, never
//      the reverse; design-system imports nothing app-level.
const HEX_MESSAGE =
  'No hard-coded hex colors outside the design system (§5A). Reference a design-system token instead.';

const hexGuardRules = {
  'no-restricted-syntax': [
    'error',
    { selector: 'Literal[value=/#[0-9a-fA-F]{3,8}/]', message: HEX_MESSAGE },
    { selector: 'TemplateElement[value.raw=/#[0-9a-fA-F]{3,8}/]', message: HEX_MESSAGE },
  ],
};

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'src/design-system/reference', 'coverage'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-refresh': reactRefresh,
    },
    rules: {
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      ...hexGuardRules,
    },
  },
  // The design system is the ONE place tokens/colors are defined (§5A); the hex
  // guard does not apply to it. It is also the base visual layer and must not
  // import anything app-level (§6.3).
  {
    files: ['src/design-system/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': 'off',
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/app', '@/app/*', '@/features', '@/features/*', '@/shared', '@/shared/*'],
              message:
                'design-system is the base layer; it must not import app/features/shared (§6.3).',
            },
          ],
        },
      ],
    },
  },
  // shared/ is non-visual cross-feature code: no design-system, features, or app.
  {
    files: ['src/shared/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: [
                '@/design-system',
                '@/design-system/*',
                '@/features',
                '@/features/*',
                '@/app',
                '@/app/*',
              ],
              message:
                'shared holds non-visual helpers; it must not import design-system/features/app.',
            },
          ],
        },
      ],
    },
  },
  // A feature is a vertical slice: it composes design-system/shared but never the
  // app shell (§6.2, §14).
  {
    files: ['src/features/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/app', '@/app/*'],
              message: 'features must not import the app shell (§6.2).',
            },
          ],
        },
      ],
    },
  },
  // Tests may render anything and assert on it.
  {
    files: ['tests/**/*.{ts,tsx}'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: { 'no-restricted-syntax': 'off' },
  },
);
