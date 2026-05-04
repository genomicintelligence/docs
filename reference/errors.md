# Error reference

Every non-2xx response uses the unified envelope:

```json
{
  "error": {
    "code": "<machine_readable_snake_case>",
    "message": "<human-readable summary>",
    "request_id": "<server-assigned id>",
    "details": "<optional, code-specific>"
  }
}
```

`error.code` is the **authoritative discriminator** — never parse
`error.message`. The same `request_id` appears on the `X-Request-Id`
response header and on every server log line for the request. Quote it
in support tickets.

`error.details` is **typed per code** in the OpenAPI schema (Pydantic
models in `gpu_service/api/schemas/responses.py`). Switch on `code`
first, then read `details`. Codes not listed in the "structured
details" section below either carry no `details` or a free-form
payload and should be treated as opaque.

## `error.code` catalogue

| HTTP | `error.code` | Cause |
|---|---|---|
| 400 | `bad_request` | HTTP-level precondition (e.g. `Prefer: respond-async` with non-JSON `Accept`). |
| 401 | `unauthorized` | Missing/malformed `Authorization`, or key not registered. Response always carries `WWW-Authenticate: Bearer …` per RFC 6750 §3.1; the `error=` parameter is `invalid_request` for a malformed/missing header, `invalid_token` for an unrecognised key. The JSON `error.code` is `unauthorized` in both cases. |
| 403 | `forbidden` | Key registered but disabled. |
| 404 | `not_found` | Unknown route, unknown job, or cross-tenant access (returns 404 not 403 to prevent id enumeration). |
| 404 | `model_not_found` | `model` field references an unknown model. `error.details.available_models` lists alternatives. |
| 409 | `conflict` | Reserved (e.g. busy-model unload conflict). |
| 410 | `job_expired` | Async result evicted from the in-memory store (24 h TTL or process restart). |
| 413 | `payload_too_large` | Body exceeded the 16 MiB hard cap. |
| 413 | `sync_too_large` | Reserved. Schema-typed (`SyncTooLargeDetails`) for future use; no partner-visible endpoint emits it today. See [`./limits.md`](./limits.md) for soft per-task async-opt-in guidance. |
| 415 | `unsupported_format` | The task's `Accept` / `?format=` value is not in its allowed text-format set (e.g. `gff3` requested on a task that only emits `bed`). |
| 422 | `validation_failed` | Pydantic rejection. `error.details` is the FastAPI errors array; `error.message` summarises the first issue. |
| 422 | `task_not_supported_by_model` | Model exists but is registered for a different task. `error.details.{task,supported_tasks}`. |
| 429 | `too_many_requests` | Concurrency cap, per-key rate cap, **or** edge per-IP cap reached. All three paths emit `{error: {code: "too_many_requests", …}}` and `Retry-After`; the application paths additionally emit `RateLimit-*` headers (see [`./limits.md`](./limits.md)). The edge path's `error.request_id` is nginx's `$request_id` (32 hex chars), not a UUID — still correlates with the edge access log. |
| 500 | `internal_error` | Unanticipated; original exception goes to Sentry, never to the wire. Quote `request_id`. |
| 503 | `model_loading` | Warm-up failed or competing load in progress. Retry after ~30 s. |
| 503 | `service_unavailable` | Reserved (startup/shutdown). |
| 504 | *(no envelope)* | Sync request exceeded the upstream read timeout (300 s). Body is the edge proxy's, **not** the unified `{error: {...}}` envelope — the only response on the contract that is not the unified error envelope. Retry the request with `Prefer: respond-async`. |

## Structured `details` shapes

| `error.code` | `error.details` shape |
|---|---|
| `validation_failed` | `{ "errors": [<FastAPI validation array>] }` — each entry has `{loc, msg, type}` (and optional `input`/`ctx`). |
| `task_not_supported_by_model` | `{ "task": "<requested task>", "supported_tasks": ["<task>", ...] }` |
| `model_not_found` | `{ "available_models": ["<model>", ...] }` |
| `sync_too_large` | `{ "sequence_length": <int bp>, "threshold": <int bp> }` |

Other codes (`unauthorized`, `forbidden`, `too_many_requests`,
`payload_too_large`, `bad_request`, `not_found`, `conflict`,
`job_expired`, `unsupported_format`, `internal_error`, `model_loading`,
`service_unavailable`) do not ship structured `details`; the
human-readable `message` is the only payload.

## Handling errors

Three buckets:

1. **Retryable transient** (`429`, `503`) — honour `Retry-After`; if
   absent, exponential backoff capped at ~30 s.
2. **Permanent** (other `4xx`) — surface `error.message` to the user;
   do not retry. `422` messages are usually deterministic and safe to
   echo verbatim.
3. **Server bug** (`5xx` other than `503`) — capture `request_id` and
   contact us. One retry is fine; tight loops are not.
