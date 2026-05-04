# Getting started

Zero to three working requests in ten minutes.

```text
BASE_URL = https://api.genomicintelligence.ai
KEY      = gi_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

If you don't have a key, email **alex@genomicintelligence.ai**.

## 1. Authenticate

Every `/v1/*` request carries a bearer key. `/health`, `/docs`,
`/redoc`, `/v1/openapi.json` are public.

```bash
curl -sS "$BASE_URL/health"
curl -sS -H "Authorization: Bearer $KEY" \
     "$BASE_URL/v1/tasks/promoter/models" | jq .
```

| HTTP | `error.code` | Cause |
|---|---|---|
| 401 | `unauthorized` | Header missing/malformed *or* key not registered. The JSON `error.code` is the same for both; the `WWW-Authenticate` header splits the cause per [RFC 6750 §3.1](https://datatracker.ietf.org/doc/html/rfc6750#section-3.1) — `error="invalid_request"` for a missing/malformed header, `error="invalid_token"` for an unrecognised key. Use this when debugging from `curl -i`; typed clients should still switch on `error.code`. |
| 403 | `forbidden` | Key disabled. |
| 429 | `too_many_requests` | Per-key concurrency cap reached. Honour `Retry-After`. |

Full catalogue: [`reference/errors.md`](reference/errors.md).

## 2. Sync inference

Promoter / splice / enhancer / chromatin return inline by default.

```bash
SEQUENCE=$(python3 -c 'print("ACGT"*500)')   # 2 kb
curl -sS -X POST "$BASE_URL/v1/tasks/promoter/predict" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d "$(jq -nc --arg s "$SEQUENCE" '{sequence:$s, sequence_name:"chr1:1000-3000"}')" \
  | jq '{regions: .data.regions, meta}'
```

Response shape:

```json
{
  "data": { "task": "promoter", "model": "g0-promoter-2000bp", "regions": [] },
  "meta": {
    "job_id": "550e8400-…",
    "task": "promoter",
    "model": "g0-promoter-2000bp",
    "cold_start": false,
    "model_load_time_ms": 0,
    "inference_time_ms": 410,
    "sequence_length": 2000,
    "task_specific_counts": { "task": "promoter", "windows_processed": 1, "regions_found": 0 }
  }
}
```

`job_id` also appears in the `X-Job-Id` response header. `cold_start`
and `model_load_time_ms` report whether the model had to be loaded
into GPU memory for this request — useful for diagnosing first-request
latency.

```python
import os, requests

resp = requests.post(
    f"{os.environ['BASE_URL']}/v1/tasks/promoter/predict",
    headers={"Authorization": f"Bearer {os.environ['KEY']}"},
    json={"sequence": "ACGT" * 500, "sequence_name": "chr1:1000-3000"},
    timeout=60,
)
resp.raise_for_status()
print(resp.json()["meta"]["inference_time_ms"], "ms")
```

## 3. Async inference

Long inputs should opt into async with `Prefer: respond-async`.

Every successful response — sync `200`, async-submit `202`, completed-job
`200` — uses the same `{data, meta}` envelope. The same client code path
parses all three; HTTP status discriminates progress vs. terminal.

```bash
SEQUENCE=$(python3 -c 'print("ACGT"*30000)')
JOB_ID=$(curl -sS -X POST "$BASE_URL/v1/tasks/annotation/predict" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -H "Prefer: respond-async" \
  -d "$(jq -nc --arg s "$SEQUENCE" '{sequence:$s, sequence_name:"chr8:1-120000"}')" \
  | jq -r .data.job_id)

# HTTP status is the discriminator: 202 → still running, 200 → done,
# 4xx/5xx → terminal failure.
while true; do
  STATUS=$(curl -sS -o /tmp/job.json -w "%{http_code}" \
    -H "Authorization: Bearer $KEY" \
    "$BASE_URL/v1/tasks/jobs/$JOB_ID")
  case "$STATUS" in
    200) jq '.meta' /tmp/job.json; break ;;
    202) sleep 2 ;;
    *)   jq '.error' /tmp/job.json >&2; exit 1 ;;
  esac
done
```

```python
import time, requests

submit = requests.post(
    f"{BASE_URL}/v1/tasks/annotation/predict",
    headers={
        "Authorization": f"Bearer {KEY}",
        "Prefer": "respond-async",
    },
    json={"sequence": "ACGT" * 30000, "sequence_name": "chr8:1-120000"},
)
submit.raise_for_status()
job_id = submit.json()["data"]["job_id"]   # 202 envelope: {data, meta}

while True:
    r = requests.get(
        f"{BASE_URL}/v1/tasks/jobs/{job_id}",
        headers={"Authorization": f"Bearer {KEY}"},
    )
    if r.status_code == 202:
        time.sleep(2); continue
    if not r.ok:
        raise RuntimeError(r.json().get("error"))
    data, meta = r.json()["data"], r.json()["meta"]
    break
```

While a job is running, the `202` body from `GET /v1/tasks/jobs/{job_id}`
is also `{data, meta}`; `data.progress` carries `current_percent`,
`message`, and `elapsed_seconds`. No separate endpoint needed.

Async submit response shape (status `202`):

```json
{
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "accepted",
    "links": { "result": "/v1/tasks/jobs/550e8400-…" }
  },
  "meta": { "job_id": "550e8400-…", "task": "annotation", "mode": "async" }
}
```

## 4. Retries

Sync requests are short — a plain retry usually succeeds. For async,
retrying a `POST` issues a *new* job; if you already have a `job_id`,
read the result via `GET /v1/tasks/jobs/{job_id}` instead.

Owner-scoped: a job created by your `client_id` returns `404` for any
other caller — your jobs are private.

## 5. Rate limits

On `429`, honour `Retry-After`. `RateLimit-*` response headers carry
the per-request bucket state. Per-key caps:
[`reference/limits.md`](reference/limits.md).

## 6. Logging

Every request emits one structured server log line with `request_id`,
`client_id`, `tier`, and the request path. The request body is not
logged — sequences and predictions stay out of logs. The one exception
is `options.description` on the expression task: it is logged verbatim
and can appear in Sentry breadcrumbs on errors. Don't put confidential
content in `options.description`.

## 7. Next

- [`reference/errors.md`](reference/errors.md) — every `error.code`.
- [`reference/limits.md`](reference/limits.md) — per-task length
  caps, per-key rate quotas, async TTL.
- `/v1/openapi.json` — generate a typed client. Each request
  schema has an `example` you can copy.
