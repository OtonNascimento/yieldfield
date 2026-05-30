# Yieldfield frontend

UI only. Composes the in-repo **design system** and owns **zero** business logic
(PROJECT_CONTEXT §6.2). React 18 + TypeScript (strict) + Vite.

## Layout (see `docs/ARCHITECTURE.md`)

| Path                 | Role                                                                                         |
| -------------------- | -------------------------------------------------------------------------------------------- |
| `src/design-system/` | The single visual source of truth: tokens, theme, primitives, charts, status map (§5A, §6.3) |
| `src/app/`           | Composition root — providers, routing, shell                                                 |
| `src/features/`      | Vertical product slices (findings, reconciliation, connectors, dashboard)                    |
| `src/shared/`        | Cross-feature, non-visual helpers + generated API client wiring                              |
| `src/config/`        | Typed, public-only env access (§16)                                                          |

## Boundary rules (enforced by lint, not convention)

- **No hard-coded hex outside `design-system/`** — Stylelint (`color-no-hex`) for CSS,
  ESLint (`no-restricted-syntax`) for TS/TSX. Tokens are the one exception (§5A).
- **Layer direction** — features → design-system/shared, never the reverse;
  design-system imports nothing app-level (ESLint `no-restricted-imports`).
- **Charts come from `design-system/charts/`, never a third-party chart library** (§5A).

## Commands

```bash
npm install
npm run dev            # Vite dev server → http://localhost:5173
npm run build          # tsc -b (strict type-check) + vite build
npm run lint           # ESLint (hex + boundary guards)
npm run lint:css       # Stylelint (CSS hex guard)
npm run format:check   # Prettier
npm run test           # Vitest
```

## Notes

- The typed API client is **generated** from `contracts/` (§10) — wired in Slice 4;
  never hand-write API types.
- The delivered design-system reference files are ported in Slice 4; see
  `src/design-system/reference/README.md`.
