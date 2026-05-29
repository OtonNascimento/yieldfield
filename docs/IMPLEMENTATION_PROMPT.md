# Yieldfield — Implementation Kickoff Prompt (for Claude Code)

> Paste this as your first instruction to Claude Code in the repository root, with
> `PROJECT_CONTEXT.md` and `ARCHITECTURE.md` present in `docs/` (and the design-system
> reference files in `frontend/src/design-system/reference/`).

---

You are implementing **Yieldfield**, a Python/FastAPI + React/TypeScript platform that finds
revenue lost in usage-based billing. Two documents govern this codebase:

- `docs/PROJECT_CONTEXT.md` — product, principles, stack, security, data, design system (§5A).
- `docs/ARCHITECTURE.md` — the binding folder structure and per-directory responsibilities.

## Rule zero — these documents are the single source of truth

1. **Read both documents in full before writing any code.** Do not skim. Re-read the
   relevant section before each task.
2. **If code and these documents ever disagree, the documents win.** Conform the code to
   the documents, not the reverse.
3. **You may not deviate from, reinterpret, or "improve upon" the documented architecture,
   naming, boundaries, or stack without first stopping and asking me.** If something in the
   documents seems wrong, incomplete, or in tension with a task, **stop and surface it as a
   question** — propose options, cite the section number, and wait. Do not silently resolve it.
4. **Every directory you create must already be justified by `ARCHITECTURE.md`.** Do not
   invent directories. If a needed home does not exist in the architecture, that is a
   question for me, not a decision for you.
5. **Trace each change to a section.** In commits and PR descriptions, reference the
   governing section (e.g. "implements connector port per §17 / ARCHITECTURE connectors/base").

## Hard invariants (violating any of these is a defect, not a style choice)

- **Domain purity (§6.1, §6.4):** `backend/src/yieldfield/domain/` imports no framework — no
  FastAPI, no ORM, no HTTP, no I/O. Side effects live only in `infrastructure/`. The domain is
  pure and unit-testable.
- **UI ⟂ business logic (§6.2):** the frontend contains zero revenue/reconciliation/scoring
  rules. All financial logic is backend-only.
- **Design system is one in-repo layer (§5A, §6.3):** all tokens, theme, primitives, and charts
  live in `frontend/src/design-system/`. Feature code composes it and never defines a token,
  color, radius, or primitive. **No hard-coded hex anywhere outside the design-system layer.**
  Charts come from `design-system/charts/`, never a third-party chart library.
- **Ports & adapters (§17):** billing connectors and the scoring engine sit behind interfaces
  defined in `domain/`. Adding a connector = implementing the port in
  `infrastructure/connectors/<name>/`, touching nothing in reconciliation or UI.
- **Multi-tenancy (§11):** every data access is tenant-scoped at the data-access layer, not just
  the API. No query may cross tenant boundaries.
- **Explainable money (§6.5):** every `Finding` carries lineage (inputs, model/rule version) so
  any dollar figure is reconstructable. No black-box scores reach the user; the UI shows dollars.
- **Typed end to end (§7, §10):** strict TypeScript; Pydantic + type hints server-side; the
  OpenAPI schema in `contracts/` is the shared contract and the frontend client is generated
  from it — never hand-written.
- **Config (§16):** all config via typed, validated settings that fail fast at boot; secrets
  never committed; only public prefixed vars reach the frontend bundle.
- **Respect the fence (§4 OUT):** do **not** build telecom features, CFO/FP&A forecasting,
  SAP/Oracle/NetSuite integrations, generic dashboards, internal-fraud tooling, or full
  self-serve onboarding. Maybe-later features (§4) are not in scope until their named triggers.

## Workflow you must follow

- **Trunk-based, small PRs (§15):** one slice per branch; each PR green on lint, format,
  type-check, unit tests, contract check, and build before it is considered done.
- **Test the money paths hardest (§7):** reconciliation and scoring get the deepest unit
  coverage, including property-based tests where it fits.
- **Containerized local dev (§15):** `docker compose up` must bring the full stack up. A fresh
  engineer runs it the same day.
- **Conventional commits**, forward-only reviewed migrations (§12), feature flags for risky work.
- After each slice, **stop and report**: what you built, which sections it satisfies, what you
  assumed, and the proposed next slice. Wait for my go-ahead.

## Build order (do these as separate, reviewable slices — do not jump ahead)

**Slice 0 — Scaffold + guardrails.**
Create the exact tree from `ARCHITECTURE.md` (backend, frontend, contracts, infrastructure,
ops, docs). Wire tooling that *enforces* the invariants: Ruff + Black + mypy (strict) for
Python; ESLint + Prettier + `tsc` strict for TS; an import-boundary lint that fails if
`domain/` imports a framework, if `infrastructure/` is imported by `domain/`, or if anything
outside `design-system/` contains a hex color or defines a primitive. Set up `docker compose`
(api, workers, postgres, the columnar store, queue), CI gates, and `.env.example`. No business
logic yet. **Stop and report.**

**Slice 1 — Domain core (pure, no I/O).**
Model the canonical glossary (§8): `Tenant`, `Contract`, `Plan`, `UsageEvent`, `Invoice`,
`InvoiceLineItem`, `Reconciliation`, `Finding`, `LeakageType`, `RecoveryStatus`, `ModelRun`,
plus the `Money` value object and the severity enum aligned to the design-system status palette
(critical/high/medium/low/good, §8). Define the **connector port** and the **scoring port** as
interfaces in `domain/`. Define reconciliation rules (usage-to-invoice matching) and the finding
lifecycle as pure logic. Unit-test exhaustively. No DB, no FastAPI. **Stop and report.**

**Slice 2 — Persistence + the first connector (Stripe Billing).**
Implement PostgreSQL repositories and the columnar adapter behind the domain interfaces
(§12), with tenant scoping enforced here (§11). Implement `infrastructure/connectors/base/`
(the port) and `infrastructure/connectors/stripe_billing/` (authenticate, pull usage events,
pull invoices, verify webhook) against the Stripe sandbox. Forward-only migrations. Integration
tests against a disposable DB and the sandbox. **Stop and report.**

**Slice 3 — Application + API + ingestion/reconciliation jobs.**
Wire application use-cases (run reconciliation for tenant+window; confirm/dismiss finding;
ingest events/invoices) over the domain. Expose them through the thin FastAPI adapter under
`/api/v1` (§10) — routers per resource, Pydantic DTOs, tenant/auth/pagination dependencies,
signed inbound webhooks, the standard error envelope. Move long-running work into `workers/`
on the queue, resumable and idempotent (§13). Emit the OpenAPI schema to `contracts/`.
**Stop and report.**

**Slice 4 — Frontend: design-system layer first, then the findings slice.**
Port the delivered references (`design-system/reference/`) into the typed layer: `tokens/`
(light + dark, `--brand` invariant), `theme/` (the `[data-theme]` flip + persistence),
`primitives/` (Card, Button, Chip, Tag, Input, Segmented, Drawer, Timeline, Meter…),
`charts/` (AreaChart, BarChart, Gauge as typed React, token-colored), and `status/` (the
domain⟷status map). Honor the typography roles (Lora for numerals, DM Sans body, IBM Plex Mono
micro-labels), squared geometry, hairlines, and the reduced-motion rule (§5A). Generate the
typed client from `contracts/`. Then build the **findings** feature and a **recovered-dollars
dashboard** that compose the layer — dollars and explanations, never raw scores (§2). **Stop
and report.**

**Slice 5 — Scoring engine implementation.**
Implement the probabilistic/Bayesian scoring behind the `domain` scoring port, in
`infrastructure/scoring_engine/` (PyMC/NumPyro/sklearn), versioned and reproducible (§12), so
findings reference the exact `ModelRun`. Keep it swappable; do not let it leak into API or UI.
**Stop and report.**

## Definition of done for every slice

Tested, type-clean, lint-clean, observable (logs/metrics/traces where it runs), traceable to a
`PROJECT_CONTEXT.md` feature and an `ARCHITECTURE.md` directory, and behind a flag if risky.
The slice does exactly what was scoped — no more.

## When in doubt

Stop and ask, citing the section. A correct question now is cheaper than a wrong assumption
shipped. The documents are the source of truth; you are their faithful implementer.
