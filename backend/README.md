# Yieldfield backend

All financial/domain logic lives here (PROJECT_CONTEXT §6.2). Layered per §6 with
dependencies pointing inward toward `domain/` (see `docs/ARCHITECTURE.md`).

## Layout

| Layer | Path | Rule |
|---|---|---|
| Domain (pure core) | `src/yieldfield/domain/` | No framework/ORM/HTTP/I-O imports (§6.1, §6.4) |
| Application (use-cases) | `src/yieldfield/application/` | Orchestrates domain + infrastructure (§6.1) |
| Infrastructure (adapters) | `src/yieldfield/infrastructure/` | Implements domain ports; never imported by domain (§6.4, §17) |
| API (HTTP adapter) | `src/yieldfield/api/` | Thin; validates, calls a use-case, serializes (§10) |
| Config | `src/yieldfield/config/` | Typed settings, fail-fast at boot (§16) |
| Workers | `src/yieldfield/workers/` | Out-of-band jobs on the queue (§13) |

## Toolchain

[uv](https://docs.astral.sh/uv/) manages Python 3.12, dependencies, and process
running (ADR-0001).

```bash
uv sync                 # create the venv and install deps from uv.lock
```

## Run

```bash
uv run uvicorn yieldfield.api.main:app --reload        # API → http://localhost:8000/api/v1/health
uv run celery -A yieldfield.workers.celery_app worker  # worker (needs Redis)
```

Or bring up the whole stack from the repo root: `docker compose up` (§15).

## Quality gates (must pass; mirrored in CI, §15)

```bash
uv run ruff check .          # lint
uv run black --check .       # format check
uv run mypy                  # strict type-check (§7, §10)
uv run lint-imports          # domain-purity / inward-dependency guard (§6.1, §6.4)
uv run pytest                # unit tests (money paths get the deepest coverage, §7)
```
