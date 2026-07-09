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
  `backend/src/yieldfield/infrastructure/persistence/repositories.py` (webhook
  `find_by_id`, sweeper `list_stale_pending`).
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
