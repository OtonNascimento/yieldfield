# Yieldfield

A platform that **finds revenue lost in usage-based billing**: it connects to a SaaS
company's billing stack, continuously reconciles usage events against issued invoices,
and surfaces — in dollars — where revenue is leaking.

> **Governing documents (single source of truth).** Read these before changing code:
> [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) (product, principles, stack,
> design system §5A) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (binding folder
> structure). If code and these documents disagree, the documents win.

## Repository layout

| Path | What lives here |
|---|---|
| [`backend/`](backend/) | All financial/domain logic — Python/FastAPI, layered domain→app→infra→api (§6) |
| [`frontend/`](frontend/) | UI only — the in-repo design system + feature composition, React/TS (§6.2, §5A) |
| [`contracts/`](contracts/) | Shared OpenAPI schema + generated typed client (§10) |
| [`infrastructure/`](infrastructure/) | Dockerfiles, Terraform, K8s (§13, §15) |
| [`ops/`](ops/) | Forward-only migrations, seeds, operational scripts (§12, §15) |
| [`docs/`](docs/) | Governing documents + ADRs (§18) |

## Quickstart — the whole stack, same day (§15)

```bash
cp .env.example .env
docker compose up --build
```

Brings up: **api** (http://localhost:8000/api/v1/health), **worker** (Celery),
**frontend** (http://localhost:5173), **postgres**, **clickhouse**, **redis**.

### Or run the pieces directly

```bash
# Backend (needs Python via uv; uv installs it)
cd backend && uv sync && uv run uvicorn yieldfield.api.main:app --reload

# Frontend (hot reload)
cd frontend && npm install && npm run dev
```

## The invariants this scaffold enforces (Slice 0)

These are checked by tooling in CI, not left to convention:

- **Domain purity (§6.1, §6.4):** `import-linter` fails the build if `backend/.../domain/`
  imports any framework, ORM, HTTP, or outer layer. Run: `cd backend && uv run lint-imports`.
- **No hard-coded hex / design-system boundary (§5A, §6.3):** Stylelint (CSS) + ESLint
  (TS/TSX) reject any hex color or cross-layer import outside `frontend/src/design-system/`.
- **Typed end to end (§7, §10):** mypy `--strict` (backend) and `tsc` strict (frontend).
- **Fail-fast config (§16):** typed settings validated at boot; only `VITE_`-prefixed vars
  reach the browser bundle; secrets never committed.

## Build order

Implementation proceeds in reviewable slices — see
[`docs/IMPLEMENTATION_PROMPT.md`](docs/IMPLEMENTATION_PROMPT.md). **Slice 0 (this)** is the
scaffold + guardrails: structure, tooling, CI, and the local stack, with no business logic.
