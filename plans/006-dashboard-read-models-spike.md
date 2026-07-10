# Plan 006: Design the dashboard read models (tenant-wide findings query + recovered-dollars summary)

> **Executor instructions**: This is a DESIGN SPIKE, not an implementation
> plan. Its deliverable is one spec document; you must not modify any source
> code, schema, or the OpenAPI contract. Follow the steps, honor the STOP
> conditions, and when done update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 231534d..HEAD -- backend/src/yieldfield/api/v1/routers/findings.py backend/src/yieldfield/api/v1/schemas backend/src/yieldfield/infrastructure/persistence/repositories.py contracts/openapi/openapi.json`
> If these changed since this plan was written, read the live versions — your
> spec must describe the code as it IS.

## Status

- **Priority**: P2 — should settle before Slice 4 feature code consumes the
  findings API surface
- **Effort**: M (investigation + spec; implementation is a later, separate plan)
- **Risk**: LOW for the spike itself (docs only)
- **Depends on**: none (Plan 004 regenerates the client trivially once the
  endpoints later land — no hard ordering)
- **Category**: direction
- **Planned at**: commit `231534d`, 2026-07-07

## Why this matters

Slice 4's stated deliverables are the findings feature and a **recovered-dollars
dashboard** ("dollars, not scores" — docs/ARCHITECTURE.md reserves
`frontend/src/features/dashboard/` for exactly this). But the API cannot feed
either surface today:

1. `GET /api/v1/findings` **requires** a `reconciliation_id` query param
   (`backend/src/yieldfield/api/v1/routers/findings.py:28-40`) — there is no
   tenant-wide listing, no filter by status/leakage_type/severity, and thus no
   possible "all confirmed findings awaiting recovery" worklist, the primary
   user's daily surface.
2. No summary/rollup endpoint exists anywhere in the contract
   (`contracts/openapi/openapi.json` — verify: no path contains `summary` or
   `metrics`). The per-run `total_leakage` on reconciliation responses is
   status-agnostic and frozen at run time — it is *detected* leakage, not
   *recovered* dollars. The headline number the product is named for cannot be
   computed without a client-side fan-out over every run × every findings page,
   which the governing docs prohibit (PROJECT_CONTEXT.md §9 server-state
   posture, §13 scalability: rollups belong server-side).

Designing these two read models BEFORE Slice 4 starts prevents the frontend
from being built against a contract that cannot serve it.

## Current state (verified at `231534d`)

- `backend/src/yieldfield/api/v1/routers/findings.py:28-40` — `list_findings`
  takes `reconciliation_id: Annotated[str, Query()]` (required) and calls
  `findings.list_for_reconciliation(tenant_id, ...)`; four lifecycle POST routes
  (`review/confirm/dismiss/recover`) mutate individual findings through the
  `TransitionFinding` use-case.
- Findings carry: `customer_id`, `metric`, `leakage_type`
  (`UNBILLED_USAGE` / `MISRATED_LINE_ITEM`), `severity`, `amount` (a `Money` —
  Decimal + currency), `status` (`RecoveryStatus`: NEW → REVIEWED →
  CONFIRMED → RECOVERED / DISMISSED), `lineage`, `explanation`
  (see `backend/src/yieldfield/domain/findings/finding.py`).
- Persistence: `findings` table has per-column `tenant_id` (indexed) and
  `reconciliation_id` (indexed); money as NUMERIC(38,12) + currency CHAR(3)
  (`backend/src/yieldfield/infrastructure/persistence/models.py`).
- Pagination convention: opaque cursor, bounded limit
  (`backend/src/yieldfield/api/v1/dependencies/pagination.py`); error envelope
  `{error: {code, message, details}}`; every route tenant-scoped via
  `CurrentTenant`; OpenAPI is drift-gated.
- Repo conventions for specs: dated design docs in `docs/superpowers/specs/`
  (exemplar: `docs/superpowers/specs/2026-06-02-slice-3-application-api-jobs-design.md`
  — study its structure: decisions lettered, alternatives recorded, §-references
  to PROJECT_CONTEXT).

## Commands you will need

Read-only spike; no gates. For evidence-gathering only:

| Purpose | Command | Expected |
|---|---|---|
| Confirm no summary path | `grep -n "summary\|metrics" contracts/openapi/openapi.json` | no path definitions (only operation `summary` fields) |
| Inspect schema fields | read the files listed above | — |

## Scope

**In scope** (create exactly one file):

- `docs/superpowers/specs/<today's date>-dashboard-read-models-design.md`

**Out of scope** (do NOT touch — this is the whole point of a spike):

- ALL source code, migrations, `contracts/openapi/openapi.json`, routers,
  schemas, repositories. No implementation, no regeneration.

## Git workflow

- Branch: `advisor/006-dashboard-read-models-spike`.
- One commit, e.g. `docs(specs): dashboard read-models design (findings query + recovery summary)`.
- Stage the one new file explicitly by path.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Gather the evidence

Read, in order: the findings router/schemas/domain entity and repository
methods; the reconciliations schema (`total_leakage` semantics);
`docs/PROJECT_CONTEXT.md` §9 (state management), §10 (API architecture — it
names planned resources), §11 (tenant isolation), §13 (scalability — rollup
posture); `docs/ARCHITECTURE.md`'s frontend `dashboard/` and backend layout;
the pagination/error conventions. Note every constraint the design must honor.

### Step 2: Write the spec

The spec must contain, at minimum:

1. **Problem statement** — the two gaps above, with file:line evidence.
2. **Proposed endpoint A: tenant-wide findings listing.** Extend
   `GET /api/v1/findings`: make `reconciliation_id` optional; add optional
   filters `status`, `leakage_type`, `severity`, `customer_id`, and a time
   window; keep the cursor pagination contract. Specify: exact query params
   and types, response schema (reuse `FindingRead`), ordering (deterministic —
   propose severity/amount/id and record alternatives), and the repository
   method it needs (a tenant-scoped, filtered, ordered listing — name it and
   sketch its SQL WHERE shape). State the index implications (likely a
   composite on `(tenant_id, status)`; justify against the existing bare
   `tenant_id` index) as a migration note for the implementation plan.
3. **Proposed endpoint B: recovery summary.** A tenant-scoped
   `GET /api/v1/findings/summary` (record the alternative
   `/api/v1/metrics/recovery` and argue the choice): dollar totals and counts
   grouped by `status` (and optionally by `leakage_type`), over an optional
   time window. **Currency rule (non-negotiable)**: findings are Money with
   currency; totals MUST be per-currency (a map or list keyed by currency) —
   never summed across currencies. Recommend computing via direct SQL
   aggregate now (SUM over NUMERIC grouped by status+currency; the tables are
   small at current scale) with the §13 cached-read-model as the recorded
   at-scale evolution — this matches the repo's established defer-at-scale
   posture.
4. **What Slice 4 renders from each** — map dashboard tiles (recovered $,
   confirmed-awaiting-recovery $, open leakage $) and the worklist view to the
   response fields, so the API shape is validated against its consumer.
5. **Non-goals** — no new write paths, no status-history/time-series (findings
   don't store transition timestamps today — if the dashboard needs
   "recovered this month", say explicitly that it requires a transition
   timestamp column and record it as an open question, not a silent addition).
6. **Open questions for the maintainer** — enumerated, each with your
   recommendation: (a) transition timestamps (above); (b) should `severity`
   ordering be stable rank or enum order; (c) does the summary belong on the
   findings resource or a new metrics resource; (d) per-currency presentation
   when a tenant has one currency 99% of the time.
7. **Implementation sketch** — the files an implementation plan would touch
   (router, schemas, repository, migration, tests incl. OpenAPI regeneration)
   with rough effort, so the maintainer can commission it directly.

### Step 3: Self-check the spec

Re-read it against the hard invariants: every proposed query tenant-scoped at
the data layer; cursor pagination; error envelope untouched; dollars-never-
scores; no fence violations (no generic BI dashboard creep — the endpoints
serve exactly the two Slice-4 surfaces).

**Verify**: the file exists in `docs/superpowers/specs/`, follows the exemplar's
structure, and `git status --short` shows only that file.

## Test plan

Not applicable (spec only). The spec itself must ENUMERATE the tests the future
implementation plan will need (router filter/pagination pins, repository
predicate integration tests mirroring plans/001's pattern, per-currency
aggregation unit tests, OpenAPI drift regeneration).

## Done criteria

- [ ] Exactly one new file under `docs/superpowers/specs/`, matching the
      exemplar's register
- [ ] Both endpoints specified to implementable precision (params, schemas,
      repo methods, index note)
- [ ] The per-currency totals rule stated explicitly
- [ ] Open questions section present with recommendations
- [ ] No source/contract files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- You find an existing summary/rollup endpoint or a tenant-wide findings
  listing already merged (the gap closed since `231534d`).
- The spec drives you toward schema changes beyond an index + optional
  transition-timestamp question — scope creep; record as open question instead.
- Anything in PROJECT_CONTEXT §4 "OUT" appears to conflict with a proposal
  (e.g. drifting toward a generic financial dashboard) — surface the tension,
  don't resolve it.

## Maintenance notes

- The follow-on implementation plan should be commissioned only after the
  maintainer answers the open questions; it will interact with Plan 004 (one
  `npm run generate:api` refresh) and with the deferred keyset-pagination
  decision (API-4 in `docs/audits/2026-07-02-full-engineering-audit.md`) — a
  tenant-wide findings listing is the first endpoint where offset cursors may
  genuinely hurt, so the spec should say whether keyset lands with it.
