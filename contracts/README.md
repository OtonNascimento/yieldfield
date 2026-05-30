# contracts/

The shared API contract (§10). The OpenAPI schema is the single source of truth;
the frontend client is generated from it and never hand-written.

- `openapi/` — the OpenAPI schema **emitted from the backend** (Slice 3).
- `generated/` — the typed TS client the frontend imports (Slice 4).

CI runs a contract check (§15) that fails if the committed schema drifts from what
the backend produces.
