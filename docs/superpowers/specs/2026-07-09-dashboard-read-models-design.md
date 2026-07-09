# Dashboard Read Models Design — Tenant-Wide Findings Query + Recovery Summary

**Status:** Design — pending maintainer review (no code changes until the open questions in §6 are answered)
**Date:** 2026-07-09
**Branch:** `advisor/006-dashboard-read-models-spike` (HEAD at `231534d`)
**Governing docs:** `docs/PROJECT_CONTEXT.md`, `docs/ARCHITECTURE.md`
**Predecessor:** `docs/superpowers/specs/2026-06-02-slice-3-application-api-jobs-design.md`
**Related:** `docs/audits/2026-07-02-full-engineering-audit.md` (API-4, PF-2, PF-4)

> This document is binding only insofar as it stays consistent with `PROJECT_CONTEXT.md`,
> the single source of truth. Every component traces to a governing section (cited as §N).
> This is a design spike: **no code, schema, or contract file changes** accompany it. The
> follow-on implementation plan is commissioned only after §6 is resolved.

---

## 0. Problem statement

Slice 4's deliverables are the findings feature and the **recovered-dollars dashboard**
(`frontend/src/features/dashboard/` — "Recovered-dollars overview (§2: dollars, not
scores)", ARCHITECTURE.md frontend tree). The current API cannot feed either surface:

**Gap 1 — no tenant-wide findings listing.**
`GET /api/v1/findings` *requires* `reconciliation_id`
(`backend/src/yieldfield/api/v1/routers/findings.py:28-40` —
`reconciliation_id: Annotated[str, Query()]`; the committed contract marks it
`"required": true`, `contracts/openapi/openapi.json:684-696`). The repository port
exposes only `get` / `list_for_reconciliation` / `update`
(`backend/src/yieldfield/domain/findings/repositories.py:16-20`). There is no filter by
`status`, `leakage_type`, `severity`, or `customer_id` anywhere. Consequence: the primary
user's daily surface — "all confirmed findings awaiting recovery" — is unbuildable
without fetching every reconciliation run and every findings page client-side.

**Gap 2 — no summary/rollup endpoint.**
No path in `contracts/openapi/openapi.json` contains a summary or metrics resource
(verified: the only `summary` keys are OpenAPI operation-summary fields). The per-run
`total_leakage` on reconciliation responses sums **all** of the run's findings regardless
of lifecycle status (`backend/src/yieldfield/domain/reconciliation/reconciliation.py:34-39`)
— it is *detected* leakage at run time, not *recovered* dollars. The headline number the
product is named for (§2: quantified, dollar-denominated recovery) cannot be computed
today except by a client-side fan-out over every run × every findings page — which the
governing docs prohibit: §9 makes the server the single source of truth for server
entities, and §13 places rollups server-side ("Caching of expensive read models (e.g.
findings rollups)").

This spec designs the two read models that close these gaps, **before** Slice 4 builds
against a contract that cannot serve it.

---

## 1. Scope & non-goals

**In scope (design only; implementation is a later plan):**

- **Endpoint A** — extend `GET /api/v1/findings` into a tenant-wide, filterable,
  deterministically ordered, cursor-paginated listing (§3).
- **Endpoint B** — a new tenant-scoped `GET /api/v1/findings/summary` returning
  per-currency dollar totals and counts grouped by lifecycle status and leakage type (§4).
- The repository methods, index note, and test inventory the implementation plan needs.

**Non-goals (named fences, per §4 OUT "generic financial dashboards"):**

- **No new write paths.** The four lifecycle POST routes
  (`review`/`confirm`/`dismiss`/`recover`, `findings.py:58-75`) are untouched.
- **No status-history or time-series.** Findings store no transition timestamps —
  `FindingRow` has no `created_at`/`updated_at`/`status_changed_at`
  (`backend/src/yieldfield/infrastructure/persistence/models.py:149-174`), and
  `SqlAlchemyFindingRepository.update` writes only the mutable fields
  (`backend/src/yieldfield/infrastructure/persistence/repositories.py:205-218`).
  Therefore **"recovered this month" is not servable by this design**; it requires a
  transition-timestamp record and is recorded as open question §6(a), not silently added.
- **No generic BI creep.** No arbitrary `group_by`/dimension parameters, no `sort`
  parameter, no export formats, nothing cross-tenant. The two endpoints serve exactly the
  two Slice-4 surfaces (§5) and nothing else.
- **No OLAP involvement.** Findings are OLTP rows bounded by findings volume, not
  usage-event volume; §13's "OLTP stays lean" is respected because no aggregate here
  touches usage events.
- **No keyset pagination in the first cut** — see decision G for the recorded interplay
  with audit item API-4.

---

## 2. Proposed decisions

Lettered for reference; alternatives recorded inline. All are proposals pending review
(§6 carries the genuinely open ones).

| # | Decision | Resolution |
|---|---|---|
| A | Where the tenant-wide listing lives | **Extend the existing `GET /findings`** — make `reconciliation_id` optional and add optional filters. *Alternative rejected:* a separate `/findings/search` or worklist endpoint — §10 is resource-oriented; a second listing route over the same resource invites drift, and relaxing a required query param is compatible for every existing caller (they keep passing it). |
| B | Where the summary lives | **`GET /api/v1/findings/summary`**, a projection of the findings ledger. *Alternative rejected:* `GET /api/v1/metrics/recovery` — `metrics` is not among §10's named resources, would be a new resource for a single read, and a metrics namespace is exactly the "generic financial dashboards" slope §4 fences off. The summary is derived 1:1 from findings rows; it belongs on the resource it summarizes. Routing note: FastAPI matches in registration order, so `/summary` must be declared **before** `GET /findings/{finding_id}` (`findings.py:43`) or the literal segment is captured as a `finding_id`. See §6(c). |
| C | Listing order | **Deterministic: severity rank DESC (critical first), amount DESC, id ASC** — the worklist triage order: worst first, biggest dollars first, stable tiebreak. *Alternatives recorded:* amount-only (interleaves severities); id-only (stable but meaningless to the user); recency (findings carry no timestamp — impossible today, see §6(a)). Severity is stored as `Text`, so rank order requires a SQL `CASE` mirroring `Severity.rank` (`backend/src/yieldfield/domain/findings/severity.py:26-32`) — see §6(b). This ordering applies uniformly, including when `reconciliation_id` is passed — a deliberate behavior change from today's `ORDER BY id` (`repositories.py:201`); one API, one order. |
| D | Currency handling in the summary (**non-negotiable**) | **Totals are per-currency, always** — the response is a list of per-currency blocks; amounts in different currencies are **never summed together**, mirroring the domain (`Money.__add__` raises `CurrencyMismatchError`, `backend/src/yieldfield/domain/shared/money.py:57-63`). The SQL `GROUP BY` always includes `amount_currency`. |
| E | How the summary is computed | **Direct SQL aggregate now**: `SUM(amount_amount)`/`COUNT(*)` over `NUMERIC(38,12)` (`models.py:29-30`) grouped by `status, leakage_type, amount_currency`. Findings tables are small at current scale (bounded by findings, not events). The §13 **cached read model with explicit invalidation** (invalidate on finding transition and reconciliation save) is the recorded at-scale evolution — the endpoint contract does not change when it lands. This matches the repo's defer-at-scale posture (e.g. the pagination named simplification, `pagination.py:2-6`). |
| F | Time-window semantics | Findings have no timestamps, so the optional window filters on the **parent reconciliation's `executed_at`** via a join (`ReconciliationRow.executed_at`, `models.py:135`). Params are named `executed_after`/`executed_before` to say exactly which timestamp they bound. *Alternative rejected:* overlap against the reconciliation's `window_start`/`window_end` — "window" already means the billing period being reconciled; reusing the word for a query filter invites confusion, and `executed_at` matches the existing "newest first" list semantics (`api/v1/routers/reconciliations.py:68-77`). Windowing by *recovery date* is impossible until §6(a) is resolved. |
| G | Pagination internals (audit API-4) | **Keep the opaque-cursor contract; do NOT land keyset with this change.** But the repository must do SQL-side `WHERE`/`ORDER BY` (not materialize-then-filter): a tenant-wide unfiltered materialization is exactly API-4's worst case. The cursor's offset internals stay as-is (`pagination.py:2-6` names the swap-later seam). The composite ordering key (severity rank, amount, id) is a valid keyset triple, so nothing in this design blocks the later keyset migration — this endpoint is where offset cursors will first genuinely hurt, and the maintainer may choose to pull keyset forward at implementation time. |
| H | Summary response shape | **All five statuses zero-filled** in every currency block (stable shape; tiles never read an absent key — zero Money serializes as `"0"`, per the note at `api/v1/schemas/reconciliations.py:34-35`), plus a **server-derived `open` rollup** (`new + reviewed + confirmed`). Rationale: the "open leakage $" tile would otherwise require the client to add decimal strings — client-side money arithmetic is the float hazard §7 exists to prevent. The server owns every dollar figure the dashboard shows. |

---

## 3. Endpoint A — tenant-wide findings listing

### 3.1 Route and query parameters

`GET /api/v1/findings` — tenant-scoped via `CurrentTenant` (§11), unchanged path.

| Param | Type | Required | Semantics |
|---|---|---|---|
| `reconciliation_id` | `str` | **optional** (was required) | Restrict to one run — the existing behavior, preserved as a filter |
| `status` | `RecoveryStatus` enum | optional | `new` · `reviewed` · `confirmed` · `recovered` · `dismissed`; invalid value → 422 `validation_error` |
| `leakage_type` | `LeakageType` enum | optional | `unbilled_usage` · `misrated_line_item` · `unaudited_adjustment` |
| `severity` | `Severity` enum | optional | `critical` · `high` · `medium` · `low` · `good` |
| `customer_id` | `str` | optional | Exact match on the finding's customer |
| `executed_after` | `datetime` (tz-aware ISO-8601) | optional | Parent reconciliation `executed_at >=` bound; naive datetime → 422 (mirror `WindowParam._tz_aware`, `schemas/common.py:39-44`) |
| `executed_before` | `datetime` (tz-aware ISO-8601) | optional | Parent reconciliation `executed_at <` bound; `executed_before < executed_after` → 422 |
| `limit` / `cursor` | existing | optional | Unchanged: `limit` 1–200 default 50, opaque cursor, bad cursor → 400 `invalid_cursor` (`pagination.py:48-52`, `api/errors/exceptions.py:30-31`) |

Filters are single-valued and AND-combined. (Multi-valued `status` — e.g.
`?status=new&status=reviewed` — is recorded as a rejected-for-now alternative: no Slice-4
surface needs it; the worklist is `status=confirmed` and the dashboard totals come from
Endpoint B.)

**Compatibility:** relaxing a required param breaks no existing caller. The OpenAPI
`required` flag flips, so the contract is regenerated (drift gate) and Plan 004's client
refreshed. The unit pin `test_list_requires_the_reconciliation_id_filter`
(`backend/tests/unit/test_findings_router.py:86-90`) is deliberately **inverted** by the
implementation plan (bare `GET /findings` becomes 200), not accidentally broken.

### 3.2 Response

`FindingPage` — reused unchanged (`items: list[FindingRead]`, `meta: PageMeta`,
`backend/src/yieldfield/api/v1/schemas/findings.py:40-43`). `FindingRead` already carries
everything the worklist renders (§5.2): id, reconciliation_id, customer_id, metric,
leakage_type, severity, status, amount (`MoneyRead` decimal-string, §7), explanation.
No new listing DTO.

### 3.3 Ordering (deterministic)

Severity rank DESC → amount DESC → id ASC (decision C). In SQL, rank via a `CASE`
expression over the stored text values, mirroring `_SEVERITY_RANK`
(`severity.py:26-32`); the implementation must pin DB-order ↔ domain-rank equivalence
with a test (§8). Note: amount ordering compares numerics across currencies when a
tenant is multi-currency — acceptable for triage; presentation is §6(d).

### 3.4 Repository method

Extend the `FindingRepository` port (`domain/findings/repositories.py`) additively —
`list_for_reconciliation` stays untouched for existing callers:

```python
def list_for_tenant(
    self,
    tenant_id: TenantId,
    *,
    reconciliation_id: ReconciliationId | None = None,
    status: RecoveryStatus | None = None,
    leakage_type: LeakageType | None = None,
    severity: Severity | None = None,
    customer_id: str | None = None,
    executed_after: datetime | None = None,
    executed_before: datetime | None = None,
) -> Sequence[Finding]: ...
```

SQL WHERE shape (`SqlAlchemyFindingRepository`):

```
SELECT f.* FROM findings f
  [JOIN reconciliations r ON r.id = f.reconciliation_id     -- only when a bound is set]
WHERE f.tenant_id = :tenant                                  -- ALWAYS (§11)
  [AND f.reconciliation_id = :rid]
  [AND f.status = :status]
  [AND f.leakage_type = :ltype]
  [AND f.severity = :sev]
  [AND f.customer_id = :cust]
  [AND r.executed_at >= :after] [AND r.executed_at < :before]
ORDER BY <severity CASE> DESC, f.amount_amount DESC, f.id ASC
```

The tenant predicate is unconditional at the data layer (§11 — not just the API); each
other predicate appears only when its argument is non-None. The router keeps calling
`paginate()` over the result for now (decision G); pushing `LIMIT/OFFSET` into the SQL is
an acceptable implementation-plan refinement that changes no contract.

### 3.5 Index implications (migration note — for the implementation plan, not this spike)

The daily worklist query is `WHERE tenant_id = ? AND status = ?`. Today only the bare
`ix_findings_tenant_id` exists (`ops/migrations/versions/0001_oltp_schema.py:109`), so
every status-filtered read scans all of a tenant's findings — the same shape audit PF-4
called out for invoices/contracts and migration
`0004_reconciliation_read_indexes.py` fixed. Add in the next migration (`0005`):

- `ix_findings_tenant_status` on `(tenant_id, status)` — composite, prefix-compatible
  with plain tenant reads; justification: `status` is the highest-selectivity filter every
  worklist hits, and the summary's `GROUP BY` benefits from the same leading columns.
  Cheap now, painful after data (PF-4 precedent). Forward-only with a working
  `downgrade()` (§12).

Not added (recorded, deferred until usage proves them): `(tenant_id, customer_id)` on
findings; any index on `severity`/`leakage_type` (low cardinality, filtered within the
tenant+status slice). This spike proposes **no other schema change** — the only schema
items in the whole design are this index and the §6(a) transition-timestamp question.

---

## 4. Endpoint B — recovery summary

### 4.1 Route and query parameters

`GET /api/v1/findings/summary` — tenant-scoped via `CurrentTenant`; registered **before**
`/findings/{finding_id}` (decision B routing note).

| Param | Type | Required | Semantics |
|---|---|---|---|
| `executed_after` / `executed_before` | `datetime` (tz-aware) | optional | Same semantics and validation as Endpoint A (§3.1) — bounds the parent reconciliation's `executed_at` |

No `group_by` parameter: the response always carries both groupings (decision H;
cardinality is bounded at 5 statuses × 3 leakage types × the tenant's currencies —
a handful of cells). A `group_by` query knob was considered and rejected: two response
shapes for one page's needs, and a first step toward the §4-OUT generic dashboard.

### 4.2 Response schema (new DTOs in `api/v1/schemas/findings.py`)

```python
class StatusBucket(BaseModel):
    total: MoneyRead          # decimal-string amount (§7); currency repeated deliberately
    count: int

class CurrencySummary(BaseModel):
    currency: str                                        # ISO-4217, the block key
    by_status: dict[RecoveryStatus, StatusBucket]        # ALL five statuses, zero-filled
    open: StatusBucket                                   # server-derived: new + reviewed + confirmed
    by_leakage_type: dict[LeakageType, dict[RecoveryStatus, StatusBucket]]
                                                         # sparse: only types present in the data

class FindingSummaryRead(BaseModel):
    currencies: list[CurrencySummary]                    # one block per currency; [] when no findings
```

Rules made explicit:

- **Per-currency, always** (decision D, non-negotiable): every dollar figure lives inside
  a currency block; nothing is ever summed across blocks. A single-currency tenant gets a
  one-element list (§6(d)).
- **Zero-filling** `by_status` gives the dashboard a stable shape — `recovered` exists
  even when nothing is recovered yet (day-one tenants), serialized as `"0"`.
- **`open` is computed server-side** in `Money`/`Decimal` so no client ever adds money
  strings (§7 floats-never-touch-money, decision H).
- `by_leakage_type` is sparse (only observed types) to avoid asserting the full type
  matrix as contract; the client treats absence as zero **counts**, never derives dollars
  from it.

### 4.3 Computation (decision E)

One aggregate query:

```
SELECT f.status, f.leakage_type, f.amount_currency,
       SUM(f.amount_amount) AS total, COUNT(*) AS n
FROM findings f
  [JOIN reconciliations r ON r.id = f.reconciliation_id    -- only when a bound is set]
WHERE f.tenant_id = :tenant                                 -- ALWAYS (§11)
  [AND r.executed_at >= :after] [AND r.executed_at < :before]
GROUP BY f.status, f.leakage_type, f.amount_currency
```

`SUM` over `NUMERIC(38,12)` stays exact (§7); rows come back as `Decimal`. Zero-filling,
the `open` rollup, and nesting into `CurrencySummary` happen in Python over `Money`
values — grouping includes currency, so no cross-currency addition can occur by
construction.

**Repository method** (additive on the `FindingRepository` port):

```python
@dataclass(frozen=True, slots=True)
class FindingRollup:            # domain/findings/rollup.py — a read model of the ledger
    status: RecoveryStatus
    leakage_type: LeakageType
    total: Money                # Money.of(sum, currency) — currency-safe by type
    count: int

def summarize_for_tenant(
    self,
    tenant_id: TenantId,
    *,
    executed_after: datetime | None = None,
    executed_before: datetime | None = None,
) -> Sequence[FindingRollup]: ...
```

The router (or a thin `application/findings` read use-case, implementer's choice — no
orchestration is needed, so a direct repo call from the router matches the existing
`list_findings` posture) folds rollups into `FindingSummaryRead`.

**At-scale evolution (recorded, not built):** when findings volume makes the aggregate
expensive, materialize a per-tenant rollup cache with **explicit invalidation** on
finding transition and reconciliation save — §13 verbatim. Contract unchanged.

---

## 5. What Slice 4 renders from each

Validating the shapes against their only consumers (ARCHITECTURE.md frontend tree:
`features/dashboard/`, `features/findings/`).

### 5.1 Dashboard tiles (`features/dashboard/`) ← Endpoint B

| Tile | Response field |
|---|---|
| **Recovered $** (the headline) | `currencies[i].by_status.recovered.total` (+ `.count` as "N findings") |
| **Confirmed — awaiting recovery $** | `currencies[i].by_status.confirmed.total` (+ count) |
| **Open leakage $** | `currencies[i].open.total` (server-derived; the client performs no money arithmetic) |
| Leakage-type breakdown (design-system `charts/`) | `currencies[i].by_leakage_type[type][status].total` |
| Dismissed (context, if designed in) | `by_status.dismissed` |

Every dollar shown is a `MoneyRead` decimal string formatted by `shared/lib` money
formatting (§5A Lora tabular-nums) — dollars, never scores (§2).

### 5.2 Worklist (`features/findings/`) ← Endpoint A

The daily surface: `GET /findings?status=confirmed` (confirmed awaiting recovery),
secondary views `?status=new` (triage) and `?customer_id=...` (per-customer drill-in).

| Worklist column / control | Response field |
|---|---|
| Customer | `items[].customer_id` |
| Metric | `items[].metric` |
| Type chip | `items[].leakage_type` |
| Severity chip (design-system `status/` palette, §8) | `items[].severity` |
| Amount (right-aligned, tabular) | `items[].amount` |
| Explanation (row expand) | `items[].explanation` |
| Row actions | existing `POST /findings/{id}/review·confirm·dismiss·recover` |
| Run drill-in link | `items[].reconciliation_id` |
| Infinite scroll / next page | `meta.next_cursor` |

Server-state posture (§9): both reads live in TanStack Query; a transition mutation
invalidates the findings list keys **and** the summary key — the summary is server truth,
never recomputed client-side.

---

## 6. Open questions for the maintainer

Enumerated; each with a recommendation. The implementation plan should not be
commissioned until these are answered.

**(a) Transition timestamps — "recovered this month".**
Findings carry no lifecycle timestamps (§1 non-goals, evidence at `models.py:149-174`),
so this design's time window can only bound *detection* time (`executed_at`), never
*recovery* time. If the dashboard needs "recovered this month", that is a schema change.
*Recommendation:* defer from this design; when commissioned, prefer an **append-only
`finding_transitions` table** (`finding_id`, `tenant_id`, `from_status`, `to_status`,
`occurred_at`, actor) over a mutable `status_changed_at` column — §11 already demands
"every finding mutation … logged immutably", so the audit requirement and the time-series
requirement are the same table; a lone column is cheaper but lossy and only answers the
question for the *latest* transition.

**(b) Severity ordering — stable rank or enum order?**
`Severity` is a `StrEnum` stored as text; alphabetical order is meaningless
(`critical, good, high, low, medium`). The domain already defines the rank
(`Severity.rank`, `severity.py:20-32`). *Recommendation:* order by **stable rank** via a
SQL `CASE` generated from `_SEVERITY_RANK`, with a unit test importing the domain map so
DB ordering can never drift from the domain's (the TE-4 "derive expectations from the
module" pattern).

**(c) Does the summary belong on `findings` or a new `metrics` resource?**
*Recommendation:* `GET /findings/summary` (decision B). A `metrics` resource is not in
§10's resource list, and naming it invites the §4-OUT generic-dashboard slope. Revisit
only if a second, non-findings rollup ever becomes CORE — then a `metrics` namespace can
subsume this endpoint under a deprecation cycle.

**(d) Per-currency presentation when one currency covers 99% of tenants.**
*Recommendation:* the API stays strictly per-currency (decision D) with **no** "primary
currency" flag or cross-currency conversion server-side; a single-currency tenant simply
receives `currencies: [one block]` and the dashboard renders it directly, stacking
additional blocks only when they exist. Conversion/normalization is a product decision
(rates, as-of dates) that must not be smuggled in via a read model; reconciliation
already assumes homogeneous currency per tenant+window (predecessor spec §4.2), so
multi-block responses will be rare until mixed-currency reconciliation lands.

---

## 7. Implementation sketch (for the follow-on plan)

| File | Change | Effort |
|---|---|---|
| `backend/src/yieldfield/domain/findings/repositories.py` | Add `list_for_tenant` + `summarize_for_tenant` to the port (additive) | S |
| `backend/src/yieldfield/domain/findings/rollup.py` | New `FindingRollup` frozen dataclass | S |
| `backend/src/yieldfield/infrastructure/persistence/repositories.py` | Implement both: filtered/ordered SELECT with severity-rank `CASE`; aggregate `GROUP BY status, leakage_type, amount_currency` | M |
| `backend/src/yieldfield/api/v1/routers/findings.py` | Make `reconciliation_id` optional; add the five filters + window params; add `GET /summary` **before** `/{finding_id}`; fold rollups into the DTO | M |
| `backend/src/yieldfield/api/v1/schemas/findings.py` | `StatusBucket`, `CurrencySummary`, `FindingSummaryRead` | S |
| `ops/migrations/versions/0005_findings_worklist_index.py` | `ix_findings_tenant_status (tenant_id, status)`; forward-only + downgrade | S |
| `contracts/openapi/openapi.json` | Regenerate via `ops/scripts/export_openapi.py` (CI drift gate) | S |
| `backend/tests/…` | See §8 | M |

Overall: **M**. Interactions: Plan 004 needs one `npm run generate:api` refresh after the
contract lands; the API-4 keyset milestone is *not* pulled in (decision G) but this
endpoint's ordering key is keyset-ready.

---

## 8. Testing plan (enumerated for the implementation plan; nothing runs in this spike)

**Router unit tests** (extend `backend/tests/unit/test_findings_router.py`, fake repo):
- Bare `GET /findings` is 200 (inverts the existing 422 pin, §3.1) and forwards no filters.
- Each filter param is forwarded to `list_for_tenant` exactly once, typed (enum params:
  invalid value → 422 `validation_error` envelope).
- Naive `executed_after`/`executed_before` → 422; `before < after` → 422.
- Cursor pagination over the filtered listing: page walk, `next_cursor=None` on last
  page, bad cursor → 400 `invalid_cursor`.
- `GET /findings/summary`: zero-filled five-status shape, `open` = new+reviewed+confirmed
  computed server-side, money serialized as decimal strings, empty tenant → `currencies: []`.
- `/findings/summary` does not resolve as `GET /findings/{finding_id}` (route-order pin).
- Both endpoints 401 without bearer auth.

**Repository integration tests** (extend
`backend/tests/integration/test_oltp_repositories.py`, mirroring the plans/001
read-predicate pattern):
- `list_for_tenant`: tenant isolation (foreign tenant's findings never returned — §11);
  each predicate individually and combined; window join bounds on `executed_at`;
  deterministic ordering (severity rank desc, amount desc, id asc) — expected rank order
  derived from the domain `_SEVERITY_RANK`, not hardcoded.
- `summarize_for_tenant`: tenant isolation; correct sums/counts per
  (status, leakage_type, currency); **multi-currency fixture proving totals never merge
  across currencies**; NUMERIC exactness round-trip (no float drift); window bounds.

**Per-currency aggregation unit tests** (router/DTO folding layer):
- Rollups in two currencies → two blocks, each internally consistent; `open` per block.
- Zero-fill correctness when a status has no rows.

**Contract:**
- OpenAPI regeneration committed; CI drift gate green; `reconciliation_id` flips to
  `"required": false`; the summary path present.

---

## 9. Traceability

| Component | PROJECT_CONTEXT § | ARCHITECTURE directory |
|---|---|---|
| Tenant-wide filtered listing | §10 (resources, cursor pagination), §11 (tenant scoping at data layer) | `api/v1/routers/`, `infrastructure/persistence/` |
| Recovery summary read model | §2 (dollars, defensible), §9 (server truth), §13 (rollups as read models) | `api/v1/routers/`, `domain/findings/`, `infrastructure/persistence/` |
| Per-currency totals rule | §7 (exact money, no floats) | `domain/shared/money.py` (existing) |
| Composite index note | §12 (indexed tenant columns), audit PF-4 precedent | `ops/migrations/` |
| Dashboard/worklist consumption | §2, §5A, §9 | `frontend/src/features/{dashboard,findings}/` |
| Fences honored | §4 OUT (no generic dashboards) | — |
