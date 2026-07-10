# Plan 005: Give agents a root AGENTS.md entry point (with CLAUDE.md pointer)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 231534d..HEAD -- AGENTS.md CLAUDE.md ops/README.md docs/IMPLEMENTATION_PROMPT.md`
> AGENTS.md/CLAUDE.md must not exist yet; if either exists, STOP (someone wrote
> one since this plan). If ops/README.md or IMPLEMENTATION_PROMPT.md changed,
> re-verify the facts you are about to write against them.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW — two new documentation files; no code.
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `231534d`, 2026-07-07

## Why this matters

This repository's entire workflow is agent-executed plans, yet there is no root
`AGENTS.md`/`CLAUDE.md` — the knowledge an agent needs on first contact (the
"documents win" rule, the hard invariants, the exact verification commands, the
machine-local `UV_PYTHON` quirk, the commit conventions) is scattered across
`docs/PROJECT_CONTEXT.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PROMPT.md`,
and `ops/README.md`. Every session re-derives it, and sessions that skip the
derivation violate conventions (e.g. batching commits, running uv against the
blocked interpreter). One short root file fixes the recurring cost.

## Current state

- Repo root contains `README.md` (stale — it still describes the repo as
  "Slice 0 … no business logic"; a separate unplanned finding, do NOT fix it
  here) but no `AGENTS.md` and no `CLAUDE.md` (verified absent at `231534d`).
- The authoritative sources this file must point at (do not duplicate their
  content beyond the summaries below):
  - `docs/PROJECT_CONTEXT.md` + `docs/ARCHITECTURE.md` — binding product/architecture docs.
  - `docs/IMPLEMENTATION_PROMPT.md` — "Rule zero": the documents are the single
    source of truth; code conforms to docs, never the reverse; build order in
    slices; hard invariants.
  - `ops/README.md` — migration/bootstrap runbook, staging smoke checklist,
    production prerequisites, and the "Local-dev note: pinned Python vs OS
    policy (audit PR-7)" describing the `UV_PYTHON` workaround.
- Verification commands (all verified working in this repo): see the file body
  in Step 1 — they are the same set CI runs (`.github/workflows/ci.yml`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Confirm absence first | `git status --short` + check root listing | no AGENTS.md/CLAUDE.md |
| Markdown sanity | open the file; links resolve to real paths | all paths exist |

(No build/test gates change: this plan adds documentation only. Do not run the
test suite for this plan.)

## Scope

**In scope** (create only):

- `AGENTS.md` (repo root)
- `CLAUDE.md` (repo root — three-line pointer)

**Out of scope** (do NOT touch):

- `README.md` — its staleness is a separate backlog finding; fixing it here
  muddies review.
- Everything under `docs/`, `ops/`, `backend/`, `frontend/`.

## Git workflow

- Branch: `advisor/005-root-agents-md`.
- One commit, e.g. `docs: root AGENTS.md agent entry point + CLAUDE.md pointer`.
- Stage the two new files explicitly by path (never `git add -A` / `git add .`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write AGENTS.md

Create `AGENTS.md` at the repo root with exactly this content (adjust ONLY if a
drift-check fact changed):

```markdown
# AGENTS.md — how to work in this repository

Yieldfield is a multi-tenant SaaS that finds revenue lost in usage-based
billing: it ingests billing-platform data (Stripe first), reconciles usage
events against invoices, and surfaces dollar-valued, explainable findings.

## Rule zero — the documents win

`docs/PROJECT_CONTEXT.md` and `docs/ARCHITECTURE.md` are binding. If code and
documents disagree, conform the code to the documents. Never invent
directories, rename layers, or "improve" the architecture without asking.
Build order and workflow rules: `docs/IMPLEMENTATION_PROMPT.md`.

## Hard invariants (violations are defects)

- **Domain purity**: `backend/src/yieldfield/domain/` imports no framework, no
  ORM, no HTTP, no I/O (`lint-imports` enforces 4 contracts).
- **Layering**: api → application → domain, inward only. Composition happens
  ONLY in `api/v1/dependencies/`, `api/webhooks/`, `workers/`.
- **Multi-tenancy**: every data access is tenant-scoped at the data layer. The
  two sanctioned exceptions are documented in
  `infrastructure/persistence/repositories.py` (webhook `find_by_id`, sweeper
  `list_stale_pending`).
- **Money is Decimal** — never float. Findings carry lineage (explainable).
- **Frontend**: zero business logic; all tokens/colors/primitives live in
  `frontend/src/design-system/` (ESLint/Stylelint hex+boundary guards); strict
  TypeScript; the API client is generated from `contracts/openapi/openapi.json`,
  never hand-written.
- **Config**: typed pydantic-settings, fail-fast at boot; secrets never
  committed; only `VITE_`-prefixed vars reach the browser.

## Verification gates (run after every task; all must pass)

Backend, from `backend/` (Docker Desktop must be running for integration/E2E):

    uv run pytest -q
    uv run mypy src tests
    uv run ruff check .
    uv run black --check .
    uv run lint-imports
    uv run python ../ops/scripts/export_openapi.py --check   # when API surface changed

Frontend, from `frontend/`:

    npm run typecheck && npm run lint && npm run lint:css && npm run format:check && npm run test && npm run build

Full-stack smoke: `docker compose up -d --build --wait` then
`GET http://localhost:8000/api/v1/ready` → 200 all-ok. Runbook: `ops/README.md`.

## Machine-local quirk (this workstation)

`backend/.python-version` pins 3.12 (CI/Docker). The local OS policy blocks
uv-managed interpreters, so EVERY local uv command needs an allowed system
Python: PowerShell `$env:UV_PYTHON='3.14'` first. Without it uv rebuilds the
venv against the blocked 3.12. Details: `ops/README.md`, "Local-dev note".

## Workflow conventions

- Conventional commits with scope (`feat(api): …`, `test(workers): …`,
  `docs(ops): …`); ONE task per commit; never batch tasks.
- Stage files explicitly by path — never `git add -A`/`git add .` (the tree may
  hold local modifications that must not be committed).
- Migrations are forward-only in shared environments (`ops/migrations/`);
  schema changes keep ORM `models.py` and Alembic in parity (tests pin this).
- When the API surface changes, regenerate the contract:
  `uv run python ../ops/scripts/export_openapi.py` (CI fails on drift).
- OpenAPI contract: `contracts/openapi/openapi.json`. Audits and plans live in
  `docs/audits/`, `docs/superpowers/plans/`, and `plans/` (advisor plans).
```

**Verify**: every relative path referenced in the file exists in the repo
(check each with `Test-Path` or your file tools) → all true.

### Step 2: Write CLAUDE.md

Create `CLAUDE.md` at the repo root:

```markdown
# CLAUDE.md

Read `AGENTS.md` (same directory) — it is the agent entry point for this
repository. The binding product/architecture docs it points to win over code.
```

**Verify**: both files exist at root; `git status --short` shows exactly the
two new files (plus any pre-existing unrelated local modifications, which you
must NOT stage).

## Test plan

Not applicable (documentation only). The verification is path-existence and the
review below.

## Done criteria

- [ ] `AGENTS.md` and `CLAUDE.md` exist at the repo root with the content above
- [ ] Every file path referenced in AGENTS.md exists
- [ ] The commit contains exactly these two files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `AGENTS.md` or `CLAUDE.md` already exists (someone landed one first —
  reconcile instead of overwrite).
- A fact you are writing contradicts what you find in `ops/README.md` or
  `docs/IMPLEMENTATION_PROMPT.md` (they are the sources; the plan text loses).

## Maintenance notes

- When the stale-README backlog finding is fixed, keep README (human pitch) and
  AGENTS.md (agent operations) non-overlapping; link one to the other.
- When Slice 4 lands the generated-client wiring (plans/004) and dashboard spec
  (plans/006), no AGENTS.md change is needed — it already states the
  generated-client invariant generically.
- If the machine-local `UV_PYTHON` situation is ever resolved (OS policy
  change), delete that section here AND in `ops/README.md` together.
