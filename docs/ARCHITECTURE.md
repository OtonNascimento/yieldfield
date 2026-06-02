# ARCHITECTURE.md — Folder Structure & Directory Responsibilities

> **Derived from `PROJECT_CONTEXT.md`.** This document is binding only insofar as it
> stays consistent with that file. Every directory below justifies its existence by a
> principle in PROJECT_CONTEXT (referenced as §N). No placeholder directories, no vague
> buckets, no mixing of UI and business logic.

**Status:** Foundational — pre-implementation
**Derived from:** PROJECT_CONTEXT.md (2026-05-29), including §5A (Yieldfield Design System)

---

## Top-level layout

A monorepo (PROJECT_CONTEXT §14) with three first-class members: the backend (owns all
financial logic), the frontend (composes the in-repo design-system layer, owns no business
logic), and a shared contract that keeps them in sync without coupling runtimes.

```
yieldfield/
├── backend/                  # All business, domain, and data logic (Python/FastAPI)
├── frontend/                 # UI only — design-system layer + features (React/TS)
├── contracts/                # Shared API contract (OpenAPI) + generated clients
├── infrastructure/           # IaC, container, and deployment definitions
├── ops/                      # Operational tooling: migrations runner, seeds, scripts
├── docs/                     # PROJECT_CONTEXT.md, ARCHITECTURE.md, ADRs
└── docker-compose.yml        # One-command local stack (§15)
```

| Directory | Purpose | Responsibility | Files that belong | Why it exists |
|---|---|---|---|---|
| `backend/` | Home of every financial/domain rule | Own reconciliation, findings, scoring, ingestion | Python packages only | §6.2 — business logic lives only here |
| `frontend/` | Presentation layer | Render state, capture intent | React/TS: design-system layer + feature composition | §6.2 — UI never holds business rules |
| `contracts/` | Shared truth of the API | Hold OpenAPI schema + generated typed clients | Schema files, generated SDKs | §10 — one contract, no drift |
| `infrastructure/` | How the system is deployed | Declare infra, not application code | Terraform, K8s manifests, Dockerfiles | §13, §15 |
| `ops/` | Operational glue | Run migrations, seeds, maintenance | Scripts, migration entrypoints | §12, §15 |
| `docs/` | Engineering source of truth | Hold governing documents + decisions | Markdown, ADRs | §18 |

---

## `backend/` — business, domain, and data logic

Organized by the layering in PROJECT_CONTEXT §6 (domain at center, frameworks at edges)
and §14 (separation of concerns; dependencies point inward toward the domain).

```
backend/
├── src/
│   └── yieldfield/
│       ├── domain/             # Pure business core — no framework imports
│       │   ├── reconciliation/ # Usage-to-invoice matching rules
│       │   ├── findings/       # Leakage findings model + lifecycle
│       │   ├── scoring/        # Probabilistic scoring interfaces (ports)
│       │   ├── billing/        # Invoice, line item, contract, plan entities
│       │   └── shared/         # Value objects, domain errors, money type
│       │
│       ├── application/         # Use cases / orchestration of the domain
│       │   ├── reconciliation/  # "Run reconciliation for tenant+window"
│       │   ├── findings/        # "Confirm finding", "dismiss finding"
│       │   ├── ingestion/       # "Ingest usage events", "ingest invoices"
│       │   └── alerting/        # "Notify on material leakage"
│       │
│       ├── infrastructure/      # Impure edges — adapters implementing domain ports
│       │   ├── persistence/     # PostgreSQL repositories, ORM models, migrations glue
│       │   ├── analytics_store/ # Columnar (OLAP) read/write adapters
│       │   ├── connectors/      # Billing platform plugins (one package each)
│       │   │   ├── base/        # The connector PORT all connectors implement
│       │   │   ├── stripe_billing/
│       │   │   ├── metronome/
│       │   │   ├── orb/
│       │   │   └── lago/
│       │   ├── scoring_engine/  # Concrete Bayesian/ML implementations of scoring ports
│       │   ├── security/        # Secrets-at-rest: credential cipher (envelope-ready) — §11
│       │   ├── messaging/       # Queue producers/consumers, job orchestration
│       │   └── notifications/   # Slack/email outbound adapters
│       │
│       ├── api/                 # Thin HTTP adapter (FastAPI) — no business logic
│       │   ├── v1/              # Versioned routes (§10)
│       │   │   ├── routers/     # One router file per resource
│       │   │   ├── schemas/     # Pydantic request/response DTOs
│       │   │   └── dependencies/# Auth, tenant scoping, pagination helpers
│       │   ├── errors/          # Error envelope + exception handlers
│       │   └── webhooks/        # Signature-verified inbound provider webhooks
│       │
│       ├── config/              # Typed settings (Pydantic Settings) — fail-fast (§16)
│       └── workers/             # Long-running job entrypoints (ingestion, scoring)
│
└── tests/
    ├── unit/                    # Domain logic — heaviest coverage (§7 money paths)
    ├── integration/             # DB, connectors against sandboxes
    └── e2e/                     # Critical money paths end to end
```

### Backend directory responsibilities

| Directory | Purpose | Responsibility | Files that belong | Why it exists |
|---|---|---|---|---|
| `domain/` | The framework-agnostic business core | Encode financial rules and entities; stay pure and unit-testable | Entities, value objects, domain services, port interfaces | §6.1, §6.4 — frameworks must not leak into business logic |
| `domain/reconciliation/` | Matching logic | Decide whether a usage event is correctly billed | Pure matching rules, comparison logic | §4 CORE — the central job |
| `domain/findings/` | Findings model | Define a leakage finding, its types, and status lifecycle | `Finding`, `LeakageType`, `RecoveryStatus`, transitions | §4 CORE, §6.5 — findings are explainable, auditable |
| `domain/scoring/` | Scoring contract | Define the *interface* the probabilistic engine must satisfy | Port/protocol definitions only — no model code | §6.4, §17 — the math is swappable behind this seam |
| `domain/billing/` | Billing entities | Model invoices, line items, contracts, plans as domain objects | Entity definitions, invariants | §8 glossary — canonical domain terms |
| `domain/shared/` | Cross-domain primitives | Provide `Money`, IDs, domain errors | Value objects, error types | §7 — no copy-paste of primitives |
| `application/` | Use-case orchestration | Coordinate domain + infrastructure to fulfill a use case | Command/use-case handlers | §6.1 — orchestration distinct from rules |
| `infrastructure/` | The impure edge | Implement domain ports against real I/O | Adapters only — never business rules | §6.1, §7 (impure edges) |
| `infrastructure/persistence/` | OLTP access | Repositories + ORM models + migration glue for PostgreSQL | Repository impls, ORM models, mappers | §12 — source of truth |
| `infrastructure/analytics_store/` | OLAP access | Read/write high-volume events in the columnar store | Columnar adapters, query builders | §12, §13 — OLTP/OLAP separation |
| `infrastructure/connectors/` | Billing integrations | One plugin per billing platform, all implementing the same port | Connector packages | §17 — connectors are the primary growth axis |
| `infrastructure/connectors/base/` | The connector contract | Define authenticate / pull events / pull invoices / verify webhook | Abstract port, shared connector utilities | §17 — adding a connector = implementing this, nothing else |
| `infrastructure/scoring_engine/` | Concrete models | Implement the scoring port with Bayesian/ML code | PyMC/NumPyro/sklearn implementations | §6.4 — isolated so models evolve freely |
| `infrastructure/security/` | Secrets at rest | Encrypt/decrypt connector credentials behind a cipher port | `CredentialCipher` + Fernet impl | §11 — credentials encrypted at rest, envelope-ready |
| `infrastructure/messaging/` | Async backbone | Produce/consume jobs; orchestrate multi-step runs | Queue adapters, orchestration definitions | §13 — horizontal, resumable processing |
| `infrastructure/notifications/` | Outbound alerts | Send Slack/email when material leakage found | Notification adapters | §4 NICE-TO-HAVE alerting |
| `api/` | HTTP adapter | Validate input, call application services, serialize output | Routers, DTOs, dependencies | §10 — thin boundary, no logic |
| `api/v1/routers/` | Resource endpoints | One router per resource (findings, invoices, …) | FastAPI routers | §10 resource list |
| `api/v1/schemas/` | Wire contracts | Pydantic request/response models | DTOs suffixed by role (§8) | §10 — typed boundary |
| `api/v1/dependencies/` | Cross-cutting request concerns | Inject auth, tenant scope, pagination | Dependency providers | §11 tenant isolation enforced per request |
| `api/webhooks/` | Inbound provider events | Verify signatures; hand off to application layer | Webhook handlers | §11 — signed, replay-safe |
| `config/` | Typed configuration | Load + validate env once at startup | Settings classes | §16 — fail-fast config |
| `workers/` | Job entrypoints | Run ingestion/reconciliation/scoring out of band | Worker mains | §13 — stateless, scalable workers |
| `tests/unit/` | Domain correctness | Cover financial logic deterministically | Unit + property-based tests | §7 — money paths covered hardest |
| `tests/integration/` | Edge correctness | Verify adapters against real DB/sandboxes | Integration tests | §15 testing tiers |
| `tests/e2e/` | Whole-path correctness | Validate critical money paths | E2E tests | §15 |

---

## `frontend/` — UI only, built around the Yieldfield Design System

PROJECT_CONTEXT §5A and §6.3 make the design system a hard boundary that lives in **one
in-repo layer**. Because the system was delivered as references to port (token CSS + SVG
charts) rather than an installable package, this repo *does* contain a `design-system/`
directory — it is the single, authoritative home for tokens, the theme contract, and every
visual and chart primitive. No other directory may define a token, a color, or a primitive.
Feature code composes this layer and nothing else.

```
frontend/
├── src/
│   ├── design-system/          # THE design system, ported once (§5A) — single source of visual truth
│   │   ├── reference/          # Delivered originals (styles.css, charts.jsx, README.md) — read-only source
│   │   ├── tokens/             # Tokens ported to typed TS + CSS custom properties (light/dark)
│   │   ├── theme/              # Theme contract: [data-theme] flip, provider, persistence
│   │   ├── primitives/         # Card, Button, Chip, Tag, Input, Segmented, Drawer, Timeline, Meter…
│   │   ├── charts/             # AreaChart, BarChart, Gauge — ported from charts.jsx as typed components
│   │   └── status/             # critical/high/medium/low/good mapping (design ⟷ domain, §8)
│   │
│   ├── app/                    # App shell, providers, routing
│   │   ├── providers/          # Query client, auth, design-system theme provider
│   │   └── routes/             # Route definitions only
│   │
│   ├── features/               # Feature modules — vertical slices of product UI
│   │   ├── findings/           # The findings ledger experience
│   │   │   ├── components/     # Feature screens composed from design-system primitives
│   │   │   ├── hooks/          # Feature data hooks (server state)
│   │   │   └── api/            # Calls via the generated client
│   │   ├── reconciliation/
│   │   ├── connectors/         # Connect/manage billing platforms
│   │   └── dashboard/          # Recovered-dollars overview (§2: dollars, not scores)
│   │
│   ├── shared/                 # Cross-feature, non-visual app code
│   │   ├── api/                # Generated typed client wiring (from contracts/)
│   │   ├── hooks/              # Generic app hooks (pagination, etc.)
│   │   ├── lib/                # Formatting (money in Lora-ready format, dates), pure helpers
│   │   └── types/             # App-level shared types
│   │
│   └── config/                 # Typed, public-only env access (§16)
│
└── tests/                      # Component + interaction tests
```

### Frontend directory responsibilities

| Directory | Purpose | Responsibility | Files that belong | Why it exists |
|---|---|---|---|---|
| `design-system/` | The single visual source of truth | Own tokens, theme, primitives, charts, status mapping | Only design-system code | §5A, §6.3 — one layer owns the visual language |
| `design-system/reference/` | Preserve the delivered originals | Hold `styles.css`, `charts.jsx`, `README.md` unchanged as the porting source | The three delivered files, read-only | §5A — authoritative source of the language |
| `design-system/tokens/` | Typed tokens | Expose the light/dark token sets as TS + CSS vars | Token definitions | §5A — no hard-coded hex anywhere else |
| `design-system/theme/` | Theme contract | Implement `[data-theme]` flip, provider, persistence; keep `--brand` invariant | Theme provider, hook | §5A theming contract |
| `design-system/primitives/` | Visual primitives | Provide Card, Button, Chip, Tag, Input, Segmented control, Drawer, Timeline, Meter, etc. | One primitive per file | §5A component primitives; §6.3 composition not recreation |
| `design-system/charts/` | Chart primitives | Provide AreaChart, BarChart, Gauge as typed React, token-colored | Ported chart components | §5A — charts are in-repo, no chart library |
| `design-system/status/` | Status vocabulary | Map domain severity/status to the five status tokens in one place | Status map + helpers | §8 alignment — single mapping, not per-component |
| `app/` | Application composition root | Wire providers, routing, shell | App entry, provider setup, route table | §6.2 — orchestration without business logic |
| `app/providers/` | Global context | Provide query client, auth, and the design system's theme provider | Provider components | §5A — theme comes from the design-system layer |
| `app/routes/` | Navigation map | Declare routes and lazy boundaries | Route definitions | Separation of routing from features |
| `features/` | Product UI, sliced vertically | One self-contained experience per feature | Feature components/hooks/api | §14 — feature-oriented, single responsibility |
| `features/*/components/` | Feature UI | Compose design-system primitives into product screens | Components importing only from `design-system/` | §6.3 — composition, never new primitives |
| `features/*/hooks/` | Feature server-state | Fetch/cache server data for the feature | TanStack Query hooks | §9 — server state stays in the cache |
| `features/*/api/` | Feature data access | Call backend via the generated client | Thin call wrappers | §10 — typed, generated, no drift |
| `shared/` | Cross-feature, non-visual code | House app-wide helpers and client wiring | Hooks, lib, types, client setup | Avoids duplication without inventing UI |
| `shared/api/` | Client wiring | Configure the generated SDK (base URL, auth, errors) | Client config | §10 — single generated contract consumer |
| `shared/lib/` | Pure helpers | Format money/dates; pure utilities | Pure functions only | §7 — pure, testable; no UI, no business rules |
| `config/` | Frontend env | Expose only public, prefixed env vars | Typed env module | §16 — no secrets in the bundle |

> **Boundary rule:** a feature component may import from `design-system/` and `shared/`, never
> the reverse, and may **never** define a color, token, radius, or primitive of its own. Charts
> come from `design-system/charts/`, never a third-party package. Any hard-coded hex or new
> primitive outside `design-system/` is rejected at review — it violates §5A/§6.3, and §5A is
> binding.

---

## `contracts/` — the shared API contract

```
contracts/
├── openapi/                    # Source-of-truth OpenAPI schema (generated from backend)
└── generated/                  # Generated typed client(s) consumed by the frontend
```

| Directory | Purpose | Responsibility | Files that belong | Why it exists |
|---|---|---|---|---|
| `openapi/` | Canonical API contract | Hold the OpenAPI schema emitted by the backend | `openapi.json`/`.yaml` | §10 — one contract |
| `generated/` | Typed client | Provide the SDK the frontend imports | Generated TS client | §10 — eliminate hand-written drift |

---

## `infrastructure/` — deployment & infra-as-code

```
infrastructure/
├── docker/                     # Dockerfiles per service (api, workers, frontend)
├── terraform/                  # Cloud resources, networking, secrets manager wiring
└── k8s/                        # Deployment manifests / Helm charts
```

| Directory | Purpose | Responsibility | Files that belong | Why it exists |
|---|---|---|---|---|
| `docker/` | Container definitions | Build reproducible images per service | Dockerfiles | §15 — containerized everywhere |
| `terraform/` | Provisioned infra | Declare cloud infra and secrets wiring | `.tf` modules | §13, §16 |
| `k8s/` | Runtime topology | Declare how services run and scale | Manifests/Helm | §13 — horizontal scaling |

---

## `ops/` — operational tooling

```
ops/
├── migrations/                 # Versioned, forward-only DB migrations (§12)
├── seeds/                      # Deterministic seed data for local/staging
└── scripts/                    # Maintenance and one-off operational scripts
```

| Directory | Purpose | Responsibility | Files that belong | Why it exists |
|---|---|---|---|---|
| `migrations/` | Schema evolution | Hold reviewed, forward-only migrations | Migration files | §12 — migrations reviewed like code |
| `seeds/` | Reproducible data | Seed local/staging deterministically | Seed scripts | §15 — same-day local setup |
| `scripts/` | Operational glue | Run maintenance safely | Scripts | §15 |

---

## `docs/` — governing documents

```
docs/
├── PROJECT_CONTEXT.md          # The single source of truth (Phase 1)
├── ARCHITECTURE.md             # This document (Phase 2)
└── adr/                        # Architecture Decision Records
```

| Directory | Purpose | Responsibility | Files that belong | Why it exists |
|---|---|---|---|---|
| `docs/` | Engineering truth | Hold governing docs and decisions | Markdown, ADRs | §18 — code defers to these docs |
| `docs/adr/` | Decision history | Record why decisions were made/changed | One ADR per decision | §0 — locked decisions are overridable, with a trail |

---

## Dependency rule (the invariant that holds it all together)

Dependencies point **inward**, toward the domain:

```
api ─▶ application ─▶ domain ◀─ infrastructure
frontend features ─▶ design-system ─▶ tokens
frontend ─▶ contracts ─▶ (backend's published schema)
```

- `domain/` imports nothing from `api/`, `infrastructure/`, or any framework. (§6.1)
- `infrastructure/` implements interfaces defined in `domain/`; never the reverse. (§6.4, §17)
- `frontend/` depends on `contracts/`, never on `backend/` internals. (§10)
- Frontend **features depend on `design-system/`, never the reverse**, and never define their
  own tokens, colors, or primitives. The design-system layer is the only place the visual
  language exists. (§5A, §6.3)

Any proposed directory or import that violates this rule is rejected at review — it
contradicts PROJECT_CONTEXT, which is the single source of truth.
