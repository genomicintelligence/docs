# Limits reference

Authoritative source: `gpu_service/core/limits.py` (input bounds) and
`gpu_service/core/job_store.py` (TTL). Numbers here mirror those files;
the constants win on drift.

## Input length per task

Oversized/undersized inputs are rejected with `422 validation_failed`
*before* any GPU work. Sequences must contain only `A/C/G/T/N`
(case-insensitive).

| Task | Endpoint | Min bp | Max bp |
|---|---|---:|---:|
| Promoter | `POST /v1/tasks/promoter/predict` | 1 | 500,000 |
| Splice | `POST /v1/tasks/splice/predict` | 1 | 2,250,000 |
| Enhancer | `POST /v1/tasks/enhancer/predict` | 1 | 500,000 |
| Chromatin | `POST /v1/tasks/chromatin/predict` | 1 | 500,000 |
| Annotation | `POST /v1/tasks/annotation/predict` | 1 | 500,000 |
| Expression (TSS-centered) | `POST /v1/tasks/expression/predict` | 1 | 500,000 |

Body cap: 16 MiB. The expression model was trained on a 9,198 bp
TSS-centered window (±4,599 bp); off-length sequences are accepted
(the tokenizer truncates / pads to the model's fixed window) but
predictions on non-TSS-centered or off-length sequences are not
guaranteed to be biologically meaningful. If you have raw genomic
input where the TSS isn't pre-known, contact us — server-side
annotation → expression chaining can be enabled per-tenant.

## Sync delivery — timeout and guidance

Sync delivery (the default, no `Prefer` header) is **best-effort within
the upstream HTTP read timeout of 300 seconds**. A request that takes
longer than that will be terminated by the edge proxy and surface to
your client as a connection-reset / `504 gateway_timeout` (the body in
this case is the proxy's, not the unified `{error: {...}}` envelope —
the only place where that happens). Pick async whenever you expect a
request to push past ~60 s.

### Hard sync cap

No partner-visible endpoint enforces a hard sync cap today; every
task accepts sync up to its per-task max (see "Input length per task"
above). The `413 sync_too_large` error class is reserved in the
schema (`SyncTooLargeDetails`) for future use; partners do not need
to handle it on the current contract beyond switching on
`error.code`.

### Recommended async opt-in (client-side guidance, not enforced)

Use `Prefer: respond-async` when your input exceeds the threshold
below. These are calibrated against typical inference times on the
production GPU; sync still works under them, but bursty traffic plus
GPU contention can push individual requests past the 300 s proxy
window without warning.

| Task | Recommended async above |
|---|---:|
| Promoter | 100,000 bp |
| Splice | 250,000 bp |
| Enhancer | 100,000 bp |
| Chromatin | 100,000 bp |
| Annotation | 30,000 bp |
| Expression (TSS-centered) | n/a — input is the fixed 9,198 bp window; sync is always safe. |

If sync is critical for your workload and these guidelines force more
async than you can stomach, contact us — we can profile your
distribution and tune the proxy timeout for your tenant.

## Per-key quotas

Three limiters run side-by-side. All in-process, in-memory, reset on
process restart. Configured per partner — your account owner tells you
the values issued for your key. Defaults for a partner trial key:

| Setting | Default for trial keys | Enforced? |
|---|---:|---|
| Concurrent in-flight requests | 2 | ✅ — exceeds cap → `429 too_many_requests`, `Retry-After: 1`. |
| Per-minute request rate | 60 | ✅ — token bucket; capacity = `rate ÷ 6` (10-second burst, default 10). Empty bucket → `429 too_many_requests`, `Retry-After` ≈ seconds-to-next-token. |
| Edge per-IP cap | 10 r/s burst 20 on `api.*` | ✅ — at nginx, returns `429 too_many_requests` with the unified `{error: {...}}` envelope (see [`./errors.md`](./errors.md)). |

### `RateLimit-*` headers (every authenticated response)

The application emits the IETF
[httpapi-ratelimit-headers](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/)
draft set on every authenticated `2xx` and on every `429` from this
service, so you can pace from header state without inferring rate
from `429`s:

| Header | Meaning |
|---|---|
| `RateLimit-Limit` | Token-bucket capacity (= `rate_per_minute ÷ 6`). |
| `RateLimit-Remaining` | Tokens left after this request, integer. |
| `RateLimit-Reset` | Seconds until the bucket refills to full. |
| `RateLimit-Policy` | `<capacity>;w=60` — capacity per 60-second window. |
| `Retry-After` | On `429` only, seconds until at least one token is available. |

### Pacing guidance

- Pace at ~80 % of your issued `RateLimit-Limit` to leave headroom for
  bursts; serialise a small worker pool against your concurrency cap
  rather than firing N parallel requests at it.
- The token bucket and concurrency semaphore are independent: a 429
  can come from either. Both carry the same `RateLimit-*` spine, but
  only the rate-bucket 429 has a `Retry-After` calibrated against
  refill time; the concurrency 429 uses `Retry-After: 1`.

## Async result store

| Property | Value |
|---|---|
| TTL | 24 h from last activity |
| Storage | In-process |
| Persistence | None — resets on restart |

Fetch after TTL or after a restart returns `410 job_expired`.
