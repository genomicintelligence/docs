# Genomic Intelligence API — agent integration guide

You are integrating with the **Genomic Intelligence API**, a REST service for
DNA sequence analysis using transformer language models. This document is
your single entry point. Read it linearly. Every section that says "run X"
expects you to run X and observe the output before moving on.

> **Demo posture.** This is a demo deployment, not production — a shared
> single-node setup with limited resources, intended for integration
> prototyping and small-batch experiments. The `/v1` contract is real and
> stable (typed envelopes, bearer auth, IETF `RateLimit-*` headers); the
> runtime is best-effort, no SLA, support is hours not minutes. Build
> against it for prototyping; do not depend on it for anything
> load-bearing without talking to us first.

---

## 1. WHAT

- **Six atomic tasks**, each at `POST /v1/tasks/{task}/predict`:
  `promoter`, `splice`, `enhancer`, `chromatin`, `annotation`, `expression`.
- **One auth scheme**: `Authorization: Bearer gi_…` on every `/v1/*` route.
  Public routes: `/health`, `/docs`, `/redoc`, `/v1/openapi.json`.
- **One success envelope**: `{data, meta}` on every 2xx and 202.
- **One error envelope**: `{error: {code, message, request_id, details?}}`.
- **Sync default; async opt-in** via `Prefer: respond-async`. Async submit
  returns `202` with a `job_id`; poll `GET /v1/tasks/jobs/{job_id}` for
  `202` (running, with progress) → `200` (done, full result) → `4xx/5xx`
  (terminal failure).

Base URL (production): `https://api.genomicintelligence.ai`

---

## 2. PROBE

Verify connectivity in 5 seconds. The bearer key for this run is in env
var `GI_API_KEY`.

```bash
curl -sS https://api.genomicintelligence.ai/health
# Expected: {"status":"healthy","version":"YYYY.MM.DD.iter (commit)"}

curl -sS -H "Authorization: Bearer $GI_API_KEY" \
     https://api.genomicintelligence.ai/v1/tasks/promoter/models
# Expected: 200 with {task, default_model, models: [...]}.
# NB: model-listing endpoints return a flat object, not the {data, meta}
# envelope used by predict endpoints.
```

If either fails, stop and report the failure mode. Do not proceed to
DISCOVER until both succeed.

---

## 3. DISCOVER

Run the bundled quickstart to see every task return real data with real
biological sequences. ~17 seconds wall-clock end-to-end on a warm GPU.

```bash
cd client/
pip install -r requirements.txt
GI_API_KEY=$GI_API_KEY python3 quickstart.py
```

Read the output. Note the response shapes for each task — they differ in
their `data.{...}` fields, but `meta` is uniform across all six.

The contract source-of-truth is the live OpenAPI document. Fetch it any
time you need typed schemas:

```bash
curl -sS https://api.genomicintelligence.ai/v1/openapi.json | jq .
```

It carries `oneOf` discriminators on `data.task` and on `error.details`,
so generated typed clients (Python pydantic, TypeScript zod, etc.) narrow
correctly.

---

## 4. CONTRACT — three rules to encode

### Rule 1: switch on `error.code`, not on `error.message`

`error.code` is the authoritative discriminator. Catalogue:
[`reference/errors.md`](reference/errors.md). `error.message` is for humans
in logs; it can change without notice and is not part of the contract.

### Rule 2: read `RateLimit-*` headers to pace requests

Every authenticated 2xx and every 429 carries IETF `RateLimit-*` headers:

```
RateLimit-Limit:     <token-bucket capacity>
RateLimit-Remaining: <tokens left>
RateLimit-Reset:     <seconds to full bucket>
RateLimit-Policy:    <capacity>;w=60
```

The concurrency cap and rate cap are independent — a 429 can come from
either. Per-key caps: [`reference/limits.md`](reference/limits.md).

### Rule 3: opt into async above the per-task threshold

Sync delivery has an upstream proxy timeout of 300 s. For inputs above the
per-task recommended threshold (see [`reference/limits.md`](reference/limits.md)),
add `Prefer: respond-async`, capture the `job_id` from the response, and
poll `GET /v1/tasks/jobs/{job_id}`. The poll body is the same `{data,
meta}` shape; HTTP status discriminates progress (`202`) vs. terminal
(`200` / `4xx` / `5xx`).

---

## 5. EMBED

Drop [`client/gi_client.py`](client/gi_client.py) into your codebase. It is
178 lines, depends only on `requests`, and wraps the contract:

```python
from gi_client import Client, GIError

client = Client(api_key=os.environ["GI_API_KEY"])

# Sync
body = client.predict("promoter", sequence="ACGT" * 500, sequence_name="demo")
print(body["data"]["regions"], body["meta"]["inference_time_ms"])

# Async
job_id = client.submit_async(
    "annotation", sequence=long_sequence, sequence_name="chr8:1-120000",
    options={"batch_size": 8},
)
result = client.wait_for_job(job_id, on_progress=lambda p: print(p))
```

Every non-2xx raises `GIError` with `.code`, `.message`, `.request_id`,
`.details`. Switch on `.code`, not on HTTP status alone.

---

## 6. RECIPES

Runnable patterns for the most common integration shapes. Each is a
self-contained `.py` file you can read, run, and adapt.

| Intent | File |
|---|---|
| Verify connectivity | [`recipes/01_health_probe.py`](recipes/01_health_probe.py) |
| Predict promoters across a list of human gene symbols | [`recipes/02_promoters_for_gene_list.py`](recipes/02_promoters_for_gene_list.py) |
| Submit annotation async, poll with progress, handle terminal states | [`recipes/03_async_annotation_polling.py`](recipes/03_async_annotation_polling.py) |
| Make any call rate-limit-aware (read headers, pace, retry) | [`recipes/04_ratelimit_aware_retry.py`](recipes/04_ratelimit_aware_retry.py) |
| Typed error handling: bucket every `error.code` into an action | [`recipes/05_typed_error_handling.py`](recipes/05_typed_error_handling.py) |

---

## 7. HANDLE — error taxonomy

Three buckets. Map every `error.code` to one. Full catalogue in
[`reference/errors.md`](reference/errors.md).

| Bucket | When | Action |
|---|---|---|
| **Retryable transient** | `429 too_many_requests`, `503 model_loading`, `503 service_unavailable` | Honour `Retry-After`. If absent, exponential backoff capped at ~30 s. |
| **Permanent client error** | `4xx` other than `429` (`400 bad_request`, `401 unauthorized`, `403 forbidden`, `404 not_found`, `404 model_not_found`, `409 conflict`, `410 job_expired`, `413 payload_too_large`, `413 sync_too_large`, `415 unsupported_format`, `422 validation_failed`, `422 task_not_supported_by_model`) | Surface `error.message` to the caller. Do not retry. `422` messages are deterministic and safe to echo. |
| **Server bug** | `500 internal_error`, other `5xx` | Capture `request_id`, one retry max, then escalate. |

`504 gateway_timeout` is the one response on the contract that does NOT
use the unified envelope (it comes from the edge proxy, not the app).
Treat it as "switch to async" — retry the request with `Prefer:
respond-async`.

---

## 8. PERSIST

If you are an agent that runs across sessions: copy
[`snippets/AGENTS.partner.md`](snippets/AGENTS.partner.md) into your own
repo's `AGENTS.md` (or `CLAUDE.md`). It captures the three CONTRACT rules
plus the bug-report format in ~20 lines so future sessions inherit the
behaviour without re-reading this whole document.

---

## 9. Filing a bug

Email **alex@genomicintelligence.ai** with:

- `error.request_id` from the response body (also on the `X-Request-Id`
  response header).
- `X-Job-Id` from the response (set on every successful POST, sync or
  async).

---

## 10. Where to look next

- [`getting-started.md`](getting-started.md) — auth → sync → async with
  curl + Python, narrative form.
- [`reference/errors.md`](reference/errors.md) — every `error.code`.
- [`reference/limits.md`](reference/limits.md) — per-task caps, rate
  quotas, async TTL.
- [`partner-brief.md`](partner-brief.md) — one-page summary including
  expected latency and demo-posture details.
- `https://api.genomicintelligence.ai/v1/openapi.json` — live machine-readable contract.
- `https://api.genomicintelligence.ai/redoc` — rendered OpenAPI for browsing.
