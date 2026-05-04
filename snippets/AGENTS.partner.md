# Genomic Intelligence API integration

Drop this section into your repo's `AGENTS.md` (or `CLAUDE.md` /
`.cursor/rules`) so future agent sessions inherit the contract rules
without re-reading the full integration guide.

---

## Genomic Intelligence API rules

We integrate with **api.genomicintelligence.ai** (DNA sequence analysis
REST API). Documentation: https://docs.genomicintelligence.ai —
agent entry point at https://docs.genomicintelligence.ai/AGENTS.md.

When making calls to the GI API:

- **Bearer key** is read from env var `GI_API_KEY`.
- **Switch on `error.code`**, not on `error.message`. `error.code` is
  the contract; `error.message` is human-readable and may change.
  Catalogue at <https://docs.genomicintelligence.ai/reference/errors.md>.
- **Read `RateLimit-*` response headers** to pace against your issued
  caps. Both the rate cap and the concurrency cap can produce a `429`.
- **Use async for long inputs.** For inputs above the per-task
  recommended threshold (see
  <https://docs.genomicintelligence.ai/reference/limits.md>), add
  `Prefer: respond-async`, capture the `job_id`, and poll
  `GET /v1/tasks/jobs/{job_id}` until terminal (`200` success, `4xx/5xx`
  failure). Sync delivery has a 300 s upstream proxy timeout.
- **`/v1` is additive-only.** Treat unknown JSON fields as ignorable.
- **Bug reports** quote `error.request_id` and `X-Job-Id`.
- **`gi_client.py`** from the integration kit wraps the contract
  (auth, envelope parsing, async polling).

Error-code action map:

| `error.code` | HTTP | Bucket | Action |
|---|---|---|---|
| `too_many_requests` | 429 | retryable | Honour `Retry-After`. |
| `model_loading`, `service_unavailable` | 503 | retryable | Backoff capped at ~30 s. |
| `unauthorized`, `forbidden`, `not_found`, `model_not_found`, `validation_failed`, `task_not_supported_by_model`, `payload_too_large`, `sync_too_large`, `unsupported_format`, `bad_request`, `conflict`, `job_expired` | 4xx | permanent | Surface `error.message`. Do not retry. |
| `internal_error` | 500 | server bug | Capture `request_id`, one retry max, escalate. |
| (no envelope) | 504 | proxy timeout | Switch to async (`Prefer: respond-async`). |
