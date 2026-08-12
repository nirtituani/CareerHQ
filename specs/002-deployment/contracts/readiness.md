# Contract: Readiness Report

**Endpoint**: `GET /api/health/ready` · **Authentication**: none · **Satisfies**: FR-004 – FR-008

The one externally observable contract this slice changes. Liveness (`GET /api/health`) is
unchanged.

---

## Why this contract is load-bearing

The backend service's platform health check points at this endpoint. A deployment only goes live
once it answers `200`. So a readiness report that fails because a dependency was never deployed
does not merely misinform — **it prevents every deployment from completing**.

That is deliberate. It means honesty here is enforced by the deployment pipeline rather than by
good intentions.

---

## Dependency status values

| `status` | Meaning | Counts toward overall failure |
|---|---|---|
| `ok` | Configured, probed, answered successfully | — |
| `error` | Configured, probed, failed or timed out | **Yes** |
| `not_configured` | Not configured in this environment; **no probe was attempted** | No |

**Overall status uses `ok` or `degraded`** — not `error`. `degraded` is the existing vocabulary
from slice 001 and is kept deliberately: changing it would alter an endpoint's contract for
cosmetic reasons, which FR-025 forbids. Per-dependency status uses `error`; the two levels use
different words on purpose.

`not_configured` is the value FR-006 requires. Reporting an unconfigured dependency as `ok` would
turn the health check green and make the endpoint lie; omitting it entirely would leave a reader
unable to distinguish "not deployed" from "we forgot to check".

---

## Response — everything deployed (local development)

`200 OK`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "dependencies": {
    "database":       { "status": "ok", "latency_ms": 12.4 },
    "cache":          { "status": "ok", "latency_ms": 3.1 },
    "object_storage": { "status": "ok", "latency_ms": 8.7 }
  }
}
```

## Response — Postgres only (this slice's deployed environment)

`200 OK` — the deployment is healthy. Two dependencies are absent **by design**, and saying so is
not a failure.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "dependencies": {
    "database":       { "status": "ok", "latency_ms": 18.2 },
    "cache":          { "status": "not_configured" },
    "object_storage": { "status": "not_configured" }
  }
}
```

## Response — a configured dependency is unreachable

`503 Service Unavailable`

```json
{
  "status": "degraded",
  "version": "0.1.0",
  "dependencies": {
    "database":       { "status": "error", "error": "OperationalError" },
    "cache":          { "status": "not_configured" },
    "object_storage": { "status": "not_configured" }
  }
}
```

---

## Rules

1. **A dependency is probed if and only if it is configured.** The probe set is derived from
   configuration, never hardcoded.
2. **`latency_ms` appears only on `ok`.** Absent on `error`; meaningless and absent on
   `not_configured`.
3. **Overall `status` is `ok` when every *checked* dependency is `ok`.** `not_configured` entries
   are excluded from the calculation entirely — they cannot cause failure and cannot mask it.
4. **HTTP status follows overall status**: `200` for `ok`, `503` for `degraded`.
5. **Every known dependency appears in every response.** The key set is stable; only the values
   change. A consumer never has to distinguish "key missing" from "dependency missing".
6. **Failure disclosure is unchanged** (established by T068): an unauthenticated caller receives
   the exception class name only. The driver's message — which names the internal host, port, and
   database user — goes to the log. `error` is never a free-text field.
7. **A probe that exceeds the timeout is `error`**, not a hang. A health check that never returns
   is worse than one returning bad news.

---

## Forward compatibility

When slices 003 and 004 configure a cache and object storage, those entries begin reporting `ok`
or `error` **with no code change** — the values follow configuration by construction. Adding a
future dependency means adding it to the probe registry; the contract shape does not move.

---

## Test obligations

Per Principle VII, each written and failing before implementation:

| # | Given | Then |
|---|---|---|
| 1 | All dependencies configured and healthy | All three `ok`; overall `ok`; `200` |
| 2 | Cache and object storage unconfigured | Both `not_configured`; overall `ok`; `200` |
| 3 | Cache unconfigured, database unreachable | Database `error`, cache `not_configured`; overall `degraded`; `503` |
| 4 | A configured dependency fails | Response contains the exception class and **not** the driver message |
| 5 | Any configuration | All three keys present in `dependencies` |
| 6 | A configured probe exceeds the timeout | That dependency is `error`; the response still returns |

Test 3 is the one that matters most: it proves `not_configured` neither causes failure nor masks a
real one.
