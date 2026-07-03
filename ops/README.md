# ops/

Operational tooling (§12, §15).

- `migrations/` — versioned, **forward-only** DB migrations (Alembic, wired in Slice 2).
- `seeds/` — deterministic seed data for local/staging.
- `scripts/` — maintenance and one-off operational scripts.

## Applying the schema (audit PR-3)

A fresh stack has **no tables** until both steps below run. The compose stack runs them
automatically via the one-shot `migrate` service (api/worker wait for it); every other
environment runs the same two commands before starting servers:

```bash
# from backend/ (the uv project) — needs YIELDFIELD_DATABASE_URL + YIELDFIELD_CLICKHOUSE_URL
uv run alembic -c ../ops/migrations/alembic.ini upgrade head
uv run python ../ops/scripts/bootstrap_clickhouse.py
```

Migrations are forward-only in shared environments: never `downgrade` against data you
cannot recreate. Downgrades exist for local development and CI verification.
