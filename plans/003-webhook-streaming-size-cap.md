# Plan 003: Enforce the webhook body cap while streaming, not after buffering

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 231534d..HEAD -- backend/src/yieldfield/api/webhooks/router.py backend/tests/unit/test_webhooks_router.py`
> If either changed since this plan was written, compare the "Current state"
> excerpt against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW — rejects only oversized bodies; well-formed provider events are
  unaffected. Main hazard is accidentally consuming the stream twice.
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `231534d`, 2026-07-07

## Why this matters

`POST /api/v1/webhooks/{connector_id}` is unauthenticated by design (the HMAC
signature, verified after read, is the authentication). It caps payloads at
512 KiB — but the cap is enforced via a `Content-Length` precheck plus a length
check **after** `await request.body()` has already buffered the entire stream
into memory. A request sent with chunked transfer encoding (no `Content-Length`)
skips the precheck and gets fully buffered before rejection, so the in-app
byte-bound this route added deliberately (audit SE-2a) does not actually bound
memory for the one request shape an abuser would choose. Streaming the read and
aborting the moment the cumulative size crosses the cap closes the gap. (Edge
rate-limiting remains a separate documented deployment prerequisite —
`ops/README.md`, "Production prerequisites" — this fix is the in-app layer.)

## Current state

Relevant files:

- `backend/src/yieldfield/api/webhooks/router.py` — the route to change.
- `backend/tests/unit/test_webhooks_router.py` — existing router tests: fakes
  for the connector store/registration/submitter via FastAPI
  `dependency_overrides`, a `_connector(status=...)` helper, and existing 413
  pins for (a) an oversized declared `Content-Length` and (b) an oversized
  measured body. Model the new test on these.

The code as it exists today (router.py:63-77, verbatim at `231534d`):

```python
declared = request.headers.get("content-length", "")
if declared.isdigit() and int(declared) > _MAX_PAYLOAD_BYTES:
    raise WebhookPayloadTooLargeError(f"Webhook payload exceeds {_MAX_PAYLOAD_BYTES} bytes.")

connector = store.find_by_id(ConnectorId(connector_id))
if connector is None or connector.status is not ConnectorStatus.ACTIVE:
    # A non-ACTIVE connector reads exactly like a missing one: no oracle (§11, SE-5).
    raise EntityNotFoundError(f"Connector {connector_id!r} not found.")

payload = await request.body()
if len(payload) > _MAX_PAYLOAD_BYTES:  # clients may omit/underspecify content-length
    raise WebhookPayloadTooLargeError(f"Webhook payload exceeds {_MAX_PAYLOAD_BYTES} bytes.")
live = registration.build_authenticated(connector.tenant_id, connector.id)
if not live.verify_webhook(payload, stripe_signature):
    raise InvalidWebhookSignatureError("Webhook signature verification failed.")
```

`_MAX_PAYLOAD_BYTES = 512 * 1024` is defined near the top of the same file.
`WebhookPayloadTooLargeError` maps to HTTP 413 with envelope code
`payload_too_large` (`backend/src/yieldfield/api/errors/handlers.py`,
`_TYPED_ERRORS`). The error envelope shape is
`{"error": {"code": ..., "message": ..., "details": ...}}`.

Conventions: the route is `async def`; comments cite spec sections and audit IDs;
keep the cheap `Content-Length` precheck (fail fast before the DB read).

## Commands you will need

All from `backend/`. Machine note: if `uv` errors provisioning Python 3.12, set
`$env:UV_PYTHON='3.14'` first (PowerShell; see `ops/README.md`, "Local-dev note").

| Purpose | Command | Expected on success |
|---|---|---|
| Router tests | `uv run pytest tests/unit/test_webhooks_router.py -q` | all pass |
| Webhook E2E (needs Docker) | `uv run pytest tests/e2e/test_webhook_path.py -q` | all pass |
| Unit tests | `uv run pytest -m "not integration" -q` | all pass |
| Full suite | `uv run pytest -q` | all pass (1 pre-existing skip) |
| Types / lint / format / boundaries | `uv run mypy src tests` / `uv run ruff check .` / `uv run black --check .` / `uv run lint-imports` | all clean |
| OpenAPI drift (surface unchanged) | `uv run python ../ops/scripts/export_openapi.py --check` | `up to date` |

## Scope

**In scope**:

- `backend/src/yieldfield/api/webhooks/router.py`
- `backend/tests/unit/test_webhooks_router.py`

**Out of scope** (do NOT touch):

- The signature-verification flow, connector resolution order, job submission,
  `_MAX_PAYLOAD_BYTES`'s value, the error types/mapping, middleware, settings.
- Any global request-size middleware — the cap is deliberately local to the one
  unauthenticated ingress route.

## Git workflow

- Branch: `advisor/003-webhook-streaming-size-cap`.
- One commit, e.g.
  `fix(webhooks): enforce the body cap while streaming so chunked bodies cannot buffer unbounded`.
- Stage files explicitly by path (never `git add -A` / `git add .`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write the chunked-body regression test

Note upfront: this test PASSES against the current code too (the post-buffer
check also answers 413) — its job is to pin the externally visible behavior
across the Step-2 rewrite, not to fail first. The property the rewrite changes
(no full buffering before rejection) is not observable from a black-box test;
Step 3 pins the boundary semantics that only the streaming implementation
satisfies naturally, and the reviewer checks the loop shape.

In `backend/tests/unit/test_webhooks_router.py`, add a test that POSTs a body
**larger than 512 KiB with no `Content-Length` header** (chunked). With
`fastapi.testclient.TestClient` (httpx under the hood), passing an *iterator*
as `content` sends `Transfer-Encoding: chunked`:

```python
def _oversized_chunks() -> Iterator[bytes]:
    for _ in range(9):  # 9 × 64 KiB = 576 KiB > 512 KiB cap
        yield b"x" * 65536


def test_oversized_chunked_body_without_content_length_is_413() -> None:
    client = ...  # build the app + overrides exactly like the existing 413 tests
    response = client.post(
        "/api/v1/webhooks/conn-1",
        content=_oversized_chunks(),
        headers={"Stripe-Signature": "t=1,v1=irrelevant"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
```

Reuse the same app/override construction as the existing oversized-body test in
this file (same fakes, same registered ACTIVE connector) so the request reaches
the body-reading code. Confirm the request really goes out chunked: if httpx set
a `Content-Length` header anyway, the precheck (not the body path) answered the
413 and the test is not exercising what it claims — see STOP conditions.

**Verify**: `uv run pytest tests/unit/test_webhooks_router.py -q` → all pass,
including the new test (against the CURRENT code, via the post-buffer check).

### Step 2: Replace buffer-then-check with a streaming read (GREEN)

In `router.py`, replace lines 72–74 (`payload = await request.body()` and the
post-hoc check) with an incremental read that aborts mid-stream:

```python
received = 0
chunks: list[bytes] = []
async for chunk in request.stream():
    received += len(chunk)
    if received > _MAX_PAYLOAD_BYTES:
        # Enforced WHILE reading (audit SE-2a): a chunked body without
        # content-length must not buffer past the cap before rejection.
        raise WebhookPayloadTooLargeError(
            f"Webhook payload exceeds {_MAX_PAYLOAD_BYTES} bytes."
        )
    chunks.append(chunk)
payload = b"".join(chunks)
```

Keep the `Content-Length` precheck above it (cheap early exit) and everything
after (`build_authenticated`, `verify_webhook`, submission) unchanged. Note
`request.stream()` can be consumed once — ensure no other code path in this
route calls `request.body()` afterward (none does today).

**Verify**: `uv run pytest tests/unit/test_webhooks_router.py -q` → ALL pass,
including both pre-existing 413 pins, the signature tests, and Step 1's test.

### Step 3: Pin the streaming property

The behavioral tests can't observe memory, so pin the implementation shape with
a focused assertion: add to the new test (or a sibling) a fake that streams and
asserts early abort — simplest robust version: send a body of exactly
`_MAX_PAYLOAD_BYTES` (chunked) and assert 202/400-signature (i.e. NOT 413, the
boundary is `>`), and one byte over → 413. Import `_MAX_PAYLOAD_BYTES` from the
router module (tests elsewhere import private helpers — matches register).

**Verify**: `uv run pytest tests/unit/test_webhooks_router.py -q` → all pass.

### Step 4: Full gates + webhook E2E

**Verify**: `uv run pytest -q` (Docker running) → all pass including
`tests/e2e/test_webhook_path.py` (real HMAC-signed round trip — proves the
streamed `payload` bytes are identical for signature verification); then mypy /
ruff / black / lint-imports / OpenAPI check → all clean.

## Test plan

- New: oversized chunked body without `Content-Length` → 413 `payload_too_large`
  (Step 1); exact-boundary body → not 413, one-over → 413 (Step 3).
- Pattern: the existing 413 and signature tests in `test_webhooks_router.py`.
- Regression net: existing router suite + the signed E2E
  (`tests/e2e/test_webhook_path.py`) which posts a genuinely HMAC-signed payload
  and asserts the job succeeds — this catches any byte-level corruption
  introduced by the chunk join.

## Done criteria

- [ ] `uv run pytest -q` exits 0 (1 pre-existing skip)
- [ ] `grep -n "await request.body()" backend/src/yieldfield/api/webhooks/router.py`
      returns no matches
- [ ] Both new tests exist and pass; both pre-existing 413 pins still pass
- [ ] mypy / ruff / black / lint-imports / OpenAPI check all exit 0
- [ ] `git status` shows no modified files outside the two in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpt under "Current state" doesn't match the live router (drift).
- httpx/TestClient refuses to send a chunked request without `Content-Length`
  for an iterator body (verify with a debug print of `request.headers` inside a
  temporary route or by checking httpx docs for the installed version) — report
  which header it sent instead of working around it with header spoofing.
- The E2E signature test fails after Step 2 — the streamed bytes differ from
  what `request.body()` returned, which must not happen; do not "fix" the
  signature check.
- You find yourself editing anything in the Out-of-scope list.

## Maintenance notes

- If a global body-size middleware is ever added (e.g. at the edge or ASGI
  layer), this route-local guard becomes redundant but harmless; remove it only
  with a test proving the middleware covers the chunked case.
- Reviewer focus: the `>` boundary semantics (exactly-cap allowed), and that the
  `Content-Length` precheck still short-circuits before the connector DB read.
