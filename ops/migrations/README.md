# migrations/

Forward-only, reviewed-like-code Alembic migrations for the PostgreSQL OLTP schema (§12).

- Config: `alembic.ini`; environment: `env.py` (imports `metadata` from
  `yieldfield.infrastructure.persistence`).
- The database URL is supplied at runtime via `YIELDFIELD_DATABASE_URL` (or Alembic's
  `sqlalchemy.url` in CI/tests) — never committed (§16).

Apply (from `backend/`, where the `yieldfield` package is installed):

    uv run alembic -c ../ops/migrations/alembic.ini upgrade head

ClickHouse (OLAP) schema is **not** Alembic-managed; it is provisioned by the usage-event
store's `ensure_schema()` and `ops/scripts/bootstrap_clickhouse.py` (spec §6).
