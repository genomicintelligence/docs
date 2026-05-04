# Partner brief

A one-page orientation for new API partners. Pair this with the canonical
docs ([AGENTS.md](AGENTS.md), [getting-started.md](getting-started.md),
[reference/errors.md](reference/errors.md),
[reference/limits.md](reference/limits.md)) and the runnable client in
[`client/`](client/).

## What this is

**A demo deployment, not production.** A shared single-node setup with
limited resources, intended for integration prototyping and small-batch
experiments. The `/v1` contract is real and stable (typed envelopes,
bearer auth, OpenAPI 3.1 — codegen-friendly), but the runtime is
best-effort: no SLA, no status page, support is hours not minutes.

If the POC goes well and you want to depend on it for anything
load-bearing, talk to us — we'll discuss what production-shaped looks
like for your workload.

## Your key

Each partner is issued a `gi_…` bearer key. Specific caps are set
per-partner; you'll receive your numbers separately when the key is
issued.

| Field | Notes |
|---|---|
| Key format | `gi_…` |
| Concurrent in-flight cap | per-partner, typically 2–4 for new POCs |
| Per-minute request rate | per-partner, typically 60 rpm for new POCs |
| Edge per-IP cap | 10 r/s burst 20 (shared across IPs, not per-key) |
| Body cap | 16 MiB |

`RateLimit-Limit / Remaining / Reset / Policy` headers are stamped on
every authenticated 2xx and every 429. Read them to pace against your
issued caps.

## Endpoints

| Verb | Path | Notes |
|---|---|---|
| GET  | `/health` | Liveness. Public. Returns `{status, version}`. |
| GET  | `/v1/openapi.json`, `/redoc`, `/docs` | The contract. Public. |
| POST | `/v1/tasks/{task}/predict` | The six atomic tasks. Sync by default; opt into async with `Prefer: respond-async`. |
| GET  | `/v1/tasks/{task}/models` | Models registered for a task and the default. |
| GET  | `/v1/tasks/jobs/{job_id}` | Unified poll: `202` while running, `200` on success, `4xx`/`5xx` on terminal failure. |
| GET  | `/v1/tasks/jobs` | Your recent jobs. Owner-scoped — other callers get `404` for your job IDs. |

Tasks: `promoter`, `splice`, `enhancer`, `chromatin`, `annotation`,
`expression`. Per-task length caps and async-opt-in thresholds are in
[reference/limits.md](reference/limits.md).

## Expected latency (rough, warm)

| Task | ~Sync latency at the recommended size | When to go async |
|---|---|---|
| Promoter / splice / enhancer / chromatin | 0.3–10 s | inputs > ~100 kbp |
| Annotation | 1–60 s | inputs > ~30 kbp |
| Expression (fixed 9,198 bp window) | 0.5–3 s | n/a — sync is always safe |

**Cold start.** If a task's model isn't already loaded into GPU memory,
the first request pays a model-load cost. The response carries
`meta.cold_start: true` and `meta.model_load_time_ms`. Cold-start adds
**5–15 s** for the smaller models, **30–90 s** for `expression` and
`annotation`. Subsequent calls are warm.

## Filing a bug

Email **alex@genomicintelligence.ai** with:

- **`error.request_id`** from the response body (also on the
  `X-Request-Id` response header). Every server log line for the
  request carries the same value.
- **`X-Job-Id`** from the response (set on every successful POST,
  sync or async).

## Logging

Request bodies are not logged. Sequences and predictions stay out of
logs. The one exception is `options.description` on the expression
task — it is logged verbatim and can appear in Sentry breadcrumbs on
errors. Don't put confidential content in `options.description`.

## Versioning

`/v1` is additive-only — new fields, new tasks, and new models can
land without notice. Breaking changes go to `/v2` with direct partner
notice. Current version is visible at `/health`.

## Contact

**alex@genomicintelligence.ai** — key issuance, rotation, raised
caps, bug reports, anything else.
