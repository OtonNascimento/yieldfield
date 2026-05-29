# PROJECT_CONTEXT.md

> **Single source of truth** for Yieldfield's architecture and engineering direction.
> Every implementation decision must trace back to this document. If code and this
> document disagree, the document wins until the document is deliberately updated.

**Status:** Foundational — pre-implementation
**Last updated:** 2026-05-29
**Owner:** Engineering (to be assigned)
**Design system:** Yieldfield Design System (token-driven CSS + reference SVG chart primitives) — see §5A.

---

## 0. Decisions locked in this document

These were chosen as defensible defaults to keep the document concrete. Each is overridable, but until overridden it is binding.

| Area | Decision | Rationale |
|---|---|---|
| Frontend | React + TypeScript (Vite), built around the **Yieldfield Design System** | Design system ships as token-driven CSS + reference SVG charts; we port it into a typed React layer, we do not rebuild the language |
| Backend | Python (FastAPI) | Probabilistic/Bayesian core lives in the Python data ecosystem (PyMC, NumPyro, scikit-learn) |
| Primary datastore | PostgreSQL | Relational integrity for invoices/contracts/events; strong analytical SQL |
| Analytical store | Columnar warehouse (e.g. ClickHouse/BigQuery) for event-scale data | Usage events are high-volume; OLTP and OLAP separated by design |
| Async/jobs | Queue + workers (e.g. Celery/RQ or Temporal for orchestration) | Ingestion, reconciliation, scoring are long-running and retryable |
| Deploy target | Containerized (Docker) on a managed orchestrator (K8s or equivalent) | Enterprise buyers expect this; horizontal scaling for ingestion |

If you want a different stack (e.g. Node backend, or a different warehouse), change it **here first**, then Phase 2 regenerates from it.

---

## 1. Product overview

Yieldfield is a financial intelligence layer that **finds revenue lost in usage-based billing**. It connects to a SaaS company's billing stack (Stripe Billing, Metronome, Orb, Lago, or homegrown billing), continuously reconciles **usage events against issued invoices**, and surfaces — in dollars — where revenue is leaking: events that never got billed, invoices with incorrect rating, and manual adjustments nobody audited.

Beneath a deliberately plain surface ("here is the money you're missing, and where"), the system runs a probabilistic engine — Bayesian inference, anomaly detection, and forecasting — that reasons under uncertainty rather than displaying static historical metrics. The probabilistic machinery is an **engineering moat, not a marketing surface**: the user sees recovered dollars and concrete causes, not probability distributions.

**What Yieldfield is not (the fence):**
- Not a generic financial dashboard or BI tool.
- Not a telecom revenue-assurance suite (out of scope at this stage).
- Not an FP&A / forecasting product for CFOs (deferred; different buyer, different cycle).
- Not a deep SAP/Oracle/NetSuite ERP integration product in year one.
- Not "an operating system for financial risk" in its public framing — that is a long-term vision earned after product-market fit, not a launch claim.

---

## 2. Core objectives

1. **Time-to-first-value under 30 days.** A new customer connects their billing platform and sees the first concrete, dollar-denominated recoverable leakage within the first week, fully onboarded within 30 days. This is a hard product constraint, not an aspiration — it shapes architecture (fast ingestion, opinionated integrations, no multi-month data modeling).
2. **Quantified, defensible findings.** Every finding is expressed as a dollar figure with a traceable explanation ("this event at this timestamp for this customer was not billed because…"). No unexplained "anomaly score" reaches the user.
3. **Continuous, not periodic.** The system monitors in near-real-time and alerts proactively, rather than producing a monthly report.
4. **Opinionated depth over shallow breadth.** Support 3–5 billing platforms deeply rather than 30 superficially.
5. **A probabilistic core that improves with data.** Models get more accurate per-tenant the longer they run, which is the long-term defensibility.

**Validation criterion (north star for the build):** 3 usage-based SaaS companies paying ≥ $2k/month within 6 months, with at least one case study showing > $100k recovered.

---

## 3. Target users

**Primary buyer & user (year one):** Head of Billing / Billing Engineering at a Series C–D usage-based SaaS company. Technically literate, owns billing correctness, feels the pain of lost events directly, and can sign or strongly influence a contract without a 12-month CFO cycle.

**Secondary stakeholders (informed, not the buyer yet):**
- RevOps — cares about process and downstream revenue accuracy.
- Finance / Controller — consumes findings at close; becomes primary buyer only post-PMF.
- Data/Platform engineering — evaluates the integration and data handling.

**Explicitly deferred buyers:** CFO (long cycle), CTO as primary economic buyer. These inform requirements but are not the year-one target.

---

## 4. Main features and modules

Organized by priority tier, consistent with the product scope.

### CORE (defines the product)
- **Billing ingestion connectors** — deep integrations with a small set of billing platforms (Stripe Billing first; then Metronome/Orb/Lago/custom).
- **Usage-to-invoice reconciliation** — match metered usage events to issued invoice line items; surface unbilled or mis-rated events.
- **Billing anomaly detection** — probabilistic detection of invoices that deviate from expected rating given contract and usage.
- **Findings ledger** — every detected leakage as a dollar-valued, explainable, auditable record with status lifecycle (new → reviewed → confirmed → recovered/dismissed).
- **Probabilistic scoring engine** — Bayesian/ML core producing confidence-weighted findings (internal representation; user sees dollars + explanation).

### NICE-TO-HAVE (v1 if time allows)
- **Natural-language copilot** — "why is this invoice wrong?" answered from the findings + lineage.
- **Intelligent alerting** — Slack/email push when material new leakage is detected.
- **Causal narrative** — plain-language root cause ("plan X pricing changed on 14/03").
- **Relational graph view** — customer ↔ contract ↔ invoice ↔ transaction relationships.

### MAYBE-LATER (gated by explicit triggers)
- Margin-per-customer analysis — *trigger: ≥ 10 paying customers and ARR > $500k.*
- Probabilistic revenue forecasting — *trigger: core accuracy proven over 12 months.*
- Expansion to traditional subscription SaaS — *trigger: usage-based segment owned.*
- Outcome-based pricing (% of recovered revenue) — *trigger: reliable recovery benchmark exists.*

### OUT (do not build now)
Telecom revenue assurance; CFO-targeted FP&A; SAP/Oracle/NetSuite integrations; generic financial dashboards; internal-fraud tooling; fully self-serve onboarding (billing data is sensitive — human-touch onboarding stays).

---

## 5. Technical stack decisions

| Layer | Choice | Notes |
|---|---|---|
| Frontend framework | React 18 + TypeScript, Vite | Strict TS. Functional components + hooks only. |
| **Design system** | **Yieldfield Design System — ported into one in-repo typed layer (§5A)** | **Delivered as token CSS + reference SVG charts to re-create in React/TS. We port it once; all tokens, theme contract, and primitives live in that layer and nowhere else.** |
| Styling | CSS custom properties (the design system's tokens) + the design system's primitive styles | Token-driven; `[data-theme]` flip. No parallel styling system, no hard-coded hex, no ad-hoc CSS bypassing tokens. |
| Client state | Server-state library (e.g. TanStack Query) for server data; minimal local UI state | See §9. |
| Backend framework | FastAPI (Python 3.12+) | Async-first; Pydantic models as the contract boundary. |
| Probabilistic/ML | PyMC / NumPyro, scikit-learn, pandas/polars | The reasoning core. Isolated behind service interfaces. |
| OLTP database | PostgreSQL | Source of truth for tenants, contracts, invoices, findings. |
| OLAP / events | Columnar store (ClickHouse or BigQuery) | High-volume usage events and analytical scans. |
| Async processing | Task queue + workers; Temporal for multi-step orchestration | Ingestion, reconciliation runs, scoring batches. |
| API style | REST (JSON) primary; typed via OpenAPI | See §10. |
| AuthN/Z | OIDC/OAuth2 (enterprise SSO), RBAC, strict tenant isolation | See §11. |
| Infra | Docker, orchestrated (K8s); IaC (Terraform) | See §13, §15. |
| Observability | Structured logging, metrics, tracing (OpenTelemetry) | See §11, §13. |

---

## 5A. The Yieldfield Design System (binding visual contract)

The design system was delivered as **design references, not a production library**: a
token-driven `styles.css` (all light/dark tokens + component primitive styles) and a
`charts.jsx` with three hand-rolled SVG chart primitives. The README is explicit that
these are to be **re-created in our codebase's conventions** (React/TS here), porting the
*visual language* rather than copying files. This section is the binding summary; the
delivered `styles.css` + `charts.jsx` + `README.md` are the authoritative source and live
in the repo (see Phase 2).

**Aesthetic, in one line:** instrument-grade / financial-terminal — warm, editorial, squared
geometry, hairline borders, a faint background grid, straight-segment SVG charts. This
directly serves the product's "serious quantitative instrument, not candy SaaS" positioning.

**Token model (the hard contract):**
- Everything is a CSS custom property. Light tokens on `:root`; dark overrides under
  `[data-theme="dark"]`. Theme flip is a single attribute on `<html>`, persisted.
- `--brand` (`#605853`, warm taupe) is **theme-invariant** — never overridden.
- **No hard-coded hex anywhere in components.** Every surface, text, border, status,
  shadow, scrim, and chart color references a token. This is an enforced rule, not a
  preference — a single non-token color breaks the theme flip.

**Typography (three families, non-interchangeable roles):**
- **Serif — Lora:** all prominent numerals (money, counts, %, trends), titles, section
  headers. "Numbers are Lora" is the signature move. Always `font-variant-numeric:
  tabular-nums` on numeric displays.
- **Sans — DM Sans:** body, labels, nav, descriptions. (Note: the delivered `styles.css`
  header comment says "Hanken Grotesk," but the actual `--sans` token and the README both
  specify DM Sans — **DM Sans is authoritative; the comment is stale.** Flagged so it is
  not silently propagated.)
- **Mono — IBM Plex Mono:** small uppercase letter-spaced technical micro-labels only
  (eyebrows, IDs, axis ticks, tiers, timestamps).
- Base font-size 13px, optional 12–16px density scale.

**Status palette:** `critical / high / medium / low / good`, each a paired text + tint,
warm-harmonized and deliberately desaturated. These map **directly onto domain concepts**:
finding severity, recovery status, leakage type. The §8 domain enums and these status tokens
must stay aligned (see §8).

**Geometry & elevation:** squared, never pill — radii 6px cards / 4–5px controls / 2–3px
pills. Hairline 1px borders in `--line`. Restrained, near-flat card shadow; real shadow
reserved for overlays/drawers. Faint 34×34px background grid via `color-mix` so it adapts to
theme.

**Data visualization (no chart library):** hand-rolled SVG primitives — `AreaChart`
(straight polyline, gradient fill, optional gridlines, square end-marker), `BarChart`
(latest bar highlighted), `Gauge` (radial tick scale). All chart colors come from tokens so
they invert with the theme. Straight segments + square markers = the instrument read; smooth
curves and round dots are off-brand. **This means the frontend has no charting dependency —
charts are a first-class internal concern**, which affects the folder structure (Phase 2).

**Motion:** entrance animations gated behind `@media (prefers-reduced-motion: no-preference)`;
the resting state must be the visible state (never animate from hidden with `forwards` fill,
or reduced-motion users see blank charts/drawers).

**Architectural consequences (these drive §6 and Phase 2):**
1. We port the design references into a single, typed, in-repo **design-system layer** that
   owns tokens, the theme contract, primitives, and chart primitives. It is the *only* place
   visual primitives are defined.
2. Feature UI **composes** that layer; it never re-defines tokens, colors, or primitives.
3. Because charts are hand-rolled and on-brand, they belong **inside** the design-system
   layer as primitives — not pulled from a third-party chart package.
4. The status palette is a shared vocabulary between design and domain; the mapping is
   explicit and centralized, not re-derived per component.

1. **Domain at the center, frameworks at the edges.** Business logic (reconciliation, findings, scoring) does not depend on FastAPI, the ORM, or React. Frameworks are adapters around a framework-agnostic core (hexagonal / ports-and-adapters influence).
2. **UI logic and business logic never mix.** The frontend renders state and captures intent; it contains no revenue/reconciliation rules. The backend owns all financial logic. (Enforced by the folder structure in Phase 2.)
3. **The design system is a hard boundary, owned by one in-repo layer.** The Yieldfield
   Design System ships as references to port (§5A), so we re-create it once as a single typed
   design-system layer that owns all tokens, the theme contract, and every visual + chart
   primitive. Feature UI composes that layer and never forks it, re-defines tokens, or hard-codes
   color/geometry. New product UI = composition of existing primitives, not new primitives.
4. **Probabilistic core is isolated and swappable.** Models live behind explicit service interfaces so the math can evolve (or be retrained/replaced) without touching API or UI layers.
5. **Everything financial is explainable and auditable.** Each finding carries lineage: which inputs, which model/rule version, what produced it. No black-box dollar figures.
6. **Multi-tenant from day one.** Tenant isolation is an architectural invariant, not a later retrofit.
7. **Separation of OLTP and OLAP.** Transactional truth and high-volume analytical scans are physically different stores.

---

## 7. Engineering principles

- **Single responsibility everywhere** — each module, service, and directory does one thing (mirrored in Phase 2's folder rules).
- **Explicit boundaries** — modules communicate through defined interfaces/contracts, not by reaching into each other's internals.
- **Type safety end to end** — strict TypeScript on the client, Pydantic + type hints on the server; the OpenAPI schema is the shared contract.
- **Pure core, impure edges** — domain logic is pure and unit-testable; side effects (I/O, network, DB) live at the boundaries.
- **Fail loudly in dev, degrade gracefully in prod** — financial correctness errors must never be silently swallowed.
- **Test the money paths hardest** — reconciliation and scoring have the highest test coverage bar; financial logic is covered by deterministic unit tests plus property-based tests where appropriate.
- **No premature abstraction, no copy-paste either** — abstract on the third repetition.
- **Reproducibility** — model runs, ingestion runs, and reconciliation runs are versioned and replayable.
- **Small, reviewable changes** — see §14.

---

## 8. Naming conventions

**General**
- Names describe domain concepts, not implementation details (`InvoiceLineItem`, not `Row`).
- No abbreviations except a short approved glossary (`id`, `db`, `api`, `dto`).
- Booleans read as assertions: `isReconciled`, `hasAnomaly`, `canRecover`.

**Backend (Python)**
- `snake_case` for functions, variables, modules; `PascalCase` for classes; `UPPER_SNAKE_CASE` for constants.
- Files named after their primary export concept: `reconciliation_service.py`, `finding.py`.
- Pydantic schemas suffixed by role: `InvoiceCreate`, `InvoiceRead`, `FindingPublic`.

**Frontend (TypeScript/React)**
- `PascalCase` for components and component files: `FindingsTable.tsx`.
- `camelCase` for variables, functions, hooks (`useFindings`).
- Hooks always prefixed `use`.
- Types/interfaces `PascalCase`; no `I` prefix.
- One component per file; the file name equals the component name.

**Domain glossary (shared, canonical terms)**
`Tenant`, `Contract`, `Plan`, `UsageEvent`, `Invoice`, `InvoiceLineItem`, `Reconciliation`, `Finding`, `LeakageType`, `RecoveryStatus`, `ModelRun`. These names are used identically across DB, backend, API, and frontend.

**Domain ⟷ design-system status alignment.** The design system's status palette
(`critical / high / medium / low / good`, §5A) is the shared vocabulary for domain severity
and status. Domain enums that carry severity (e.g. a finding's severity) use exactly these
five tokens as their canonical values, so a backend severity maps to a design-system status
with no translation table scattered across the UI. The mapping lives in one place on the
frontend (the design-system layer), driven by the backend value.

---

## 9. State management strategy

**Frontend**
- **Server state** (anything that originates on the backend: findings, invoices, contracts) is owned by a server-state cache (TanStack Query). It is fetched, cached, invalidated — never duplicated into a global store.
- **UI state** (modals, selected rows, form drafts) is local component state or small scoped contexts. No global Redux-style store unless a concrete need proves it.
- **Single source of truth** for any server entity is the server; the client holds a cache, not a parallel truth.
- **Derived state is computed, not stored** — totals, rollups, and filters are derived at render.

**Backend**
- Stateless request handlers. All durable state in PostgreSQL / the analytical store / the queue.
- Long-running work (ingestion, reconciliation, scoring) is modeled as explicit, persisted, resumable jobs — not in-memory state.

---

## 10. API architecture

- **Style:** REST over JSON, resource-oriented, versioned under `/api/v1`.
- **Contract:** FastAPI + Pydantic generate an OpenAPI schema that is the single shared contract. The frontend's typed client is generated from it — no hand-written, drift-prone types.
- **Boundaries:** API layer is a thin adapter. It validates input, calls a domain/application service, and serializes output. No business logic in route handlers.
- **Resources (initial):** `tenants`, `connectors`, `contracts`, `plans`, `usage-events` (read/query), `invoices`, `reconciliations`, `findings`, `model-runs`, `alerts`.
- **Conventions:** plural nouns, predictable verbs, cursor-based pagination for large collections (events, findings), idempotency keys on mutating ingestion endpoints, consistent error envelope `{ error: { code, message, details } }`.
- **Async operations** return a job handle; clients poll or subscribe rather than blocking.
- **Webhooks in** (from billing platforms) and **webhooks/alerts out** (to Slack/email) are first-class, signature-verified endpoints.

---

## 11. Security considerations

- **Multi-tenant isolation is non-negotiable.** Every query is tenant-scoped; tenant boundary enforced at the data-access layer, not just the API. Consider row-level security in PostgreSQL as defense in depth.
- **AuthN:** enterprise SSO via OIDC/OAuth2; short-lived tokens; refresh handled server-side.
- **AuthZ:** role-based access control (RBAC) with least privilege; billing data is sensitive financial data.
- **Secrets:** never in code or env files committed to VCS; use a secrets manager. Connector credentials (billing platform API keys) encrypted at rest with envelope encryption.
- **Data in transit and at rest:** TLS everywhere; encryption at rest for both stores.
- **Inbound webhook verification:** verify provider signatures; reject unsigned/replayed payloads (idempotency + timestamp window).
- **Audit trail:** every finding mutation and data access on sensitive endpoints is logged immutably.
- **PII minimization:** ingest only the billing/usage fields needed for reconciliation; avoid pulling end-customer PII unless required.
- **Compliance posture:** designed toward SOC 2 readiness (access controls, audit logs, change management) given the enterprise buyer.

---

## 12. Database strategy

**OLTP — PostgreSQL (source of truth)**
- Holds: tenants, users/roles, connectors, contracts, plans, invoices, invoice line items, reconciliations, findings, model-run metadata.
- Normalized schema with explicit foreign keys; financial integrity enforced by constraints.
- Migrations are versioned, reviewed, forward-only in production (e.g. Alembic).
- Tenant column on every tenant-owned table; indexed; row-level security considered.

**OLAP — columnar store (scale)**
- Holds: raw and normalized usage events (high volume), historical scan data for model training/analytics.
- Append-mostly; partitioned by tenant + time.

**Lineage & reproducibility**
- Findings reference the exact `ModelRun` / rule version and input snapshot that produced them, so any dollar figure is reconstructable.

**Data lifecycle**
- Retention and deletion policies per tenant (contractual); deletion must cascade across both stores.

---

## 13. Scalability considerations

- **Ingestion scales horizontally** — connectors push into a queue; stateless workers scale out. Usage-event volume is the dominant load and lives in the columnar store, not OLTP.
- **Reconciliation and scoring are batched and parallelizable** per tenant, per time window; resumable and idempotent.
- **OLTP stays lean** — heavy analytical scans never hit PostgreSQL; they hit the columnar store.
- **Stateless API tier** scales horizontally behind a load balancer.
- **Backpressure & retries** — queue-based design absorbs spikes; failed jobs retry with dead-letter handling.
- **Per-tenant isolation of heavy work** so one large tenant cannot starve others (fair scheduling / quotas).
- **Caching** of expensive read models (e.g. findings rollups) with explicit invalidation.

---

## 14. Code organization standards

- **Monorepo** with clearly separated `frontend/` and `backend/` (and shared contracts), so the typed API contract is shared without coupling runtimes.
- **Feature/domain-oriented modules**, not type-oriented dumping grounds. (Concrete tree is Phase 2.)
- **Strict separation of concerns** — UI, application/use-cases, domain, and infrastructure are distinct layers; dependencies point inward toward the domain.
- **No business logic in UI; no UI concerns in domain.** Enforced structurally.
- **One responsibility per file/module**; files stay small and focused.
- **Linting/formatting enforced in CI** — Ruff + Black/equivalent (Python), ESLint + Prettier (TS). Type-checking (mypy, tsc) gates merges.
- **Conventional commits**; small PRs; every PR green on lint, type-check, and tests before merge.

---

## 15. Development workflow

- **Branching:** trunk-based with short-lived feature branches; PRs required; no direct pushes to main.
- **CI gates (must pass to merge):** lint, format check, type-check, unit tests, contract (OpenAPI) check, build.
- **Testing tiers:** unit (domain logic, heaviest on reconciliation/scoring) → integration (DB, connectors against sandboxes) → end-to-end (critical money paths).
- **Local dev:** fully containerized (`docker compose`) so a new engineer is running the stack the same day — consistent with the <30-day TTFV ethos applied internally.
- **Migrations** run in CI against a disposable DB and are reviewed like code.
- **Preview environments** per PR where feasible.
- **Definition of done:** feature behind a flag if risky, tested, documented, observable (logs/metrics/traces), and traceable to a §4 feature.

---

## 16. Environment configuration strategy

- **Twelve-factor config** — all configuration via environment variables; nothing environment-specific hardcoded.
- **Typed, validated config** — config loaded once at startup into a typed settings object (Pydantic Settings server-side; typed env module client-side); invalid config fails fast at boot.
- **Environments:** `local`, `ci`, `staging`, `production`, each with its own config source; parity kept as close as possible.
- **Secrets** come from a secrets manager, never from committed `.env`. A committed `.env.example` documents required keys with no values.
- **Feature flags** drive progressive rollout and keep risky work shippable behind a switch.
- **No secret or environment value ever reaches the frontend bundle** beyond explicitly public, prefixed variables.

---

## 17. Extensibility considerations

- **New billing connectors are plugins.** A connector implements a defined port (authenticate, pull usage events, pull invoices, verify webhook). Adding Metronome/Orb/Lago after Stripe means implementing the interface — not touching reconciliation or UI. This is the primary axis of growth and is designed for first.
- **The scoring engine is swappable** behind its interface, so models evolve or get replaced without ripple effects.
- **New leakage types** are added as typed strategies in the domain, not as scattered conditionals.
- **The design system absorbs visual change.** Because all tokens and primitives live in one
  in-repo design-system layer (§5A) that every feature composes, a token change or theme tweak
  propagates everywhere without app-level rework — provided no feature ever forked it or
  hard-coded color/geometry (see §6.3).
- **Maybe-later features have homes, not implementations.** The architecture leaves clean seams (margin analysis, forecasting) so deferred features slot in at their trigger points without restructuring.
- **API versioning** (`/api/v1`) lets contracts evolve without breaking integrated tenants.

---

## 18. How this document governs Phase 2

The folder structure document (`ARCHITECTURE.md`) is **derived from**, and must remain consistent with, this file. Specifically it must enforce structurally:
- domain ⟂ UI separation (§6.2),
- the design system as one in-repo layer every feature composes, never forks (§5A, §6.3),
- charts as in-repo design-system primitives, not a third-party dependency (§5A),
- ports-and-adapters isolation of connectors and the scoring engine (§17),
- single responsibility per directory (§7, §14),
- OLTP/OLAP and async-job separation (§12, §13).

Any folder that cannot justify its existence by a principle in this document does not belong in the architecture.
