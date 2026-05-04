"""Recipe 04 — rate-limit-aware request wrapper.

A `call()` helper that:
  - reads IETF `RateLimit-*` headers from every response and paces the
    next call to stay at ~80% of capacity
  - on `429`, honours `Retry-After`; on other 5xx, exponential backoff
    capped at 30 s
  - never retries permanent 4xx errors (catalogue:
    https://docs.genomicintelligence.ai/reference/errors.md)
  - returns the parsed `{data, meta}` body on success or raises a
    typed exception on permanent failure

Use this as a drop-in for `requests.post(...)` when you need pacing
without managing it by hand.

    GI_API_KEY=gi_… python3 04_ratelimit_aware_retry.py
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests


BASE_URL = os.environ.get("GI_BASE_URL", "https://api.genomicintelligence.ai")
API_KEY = os.environ.get("GI_API_KEY")


@dataclass
class GIError(Exception):
    status: int
    code: str
    message: str
    request_id: Optional[str] = None
    details: Any = None

    def __str__(self) -> str:
        return f"[{self.status} {self.code}] {self.message} (request_id={self.request_id})"


@dataclass
class RateLimitState:
    """Sticky pacing state between calls. Threadsafe? No — per-worker."""
    limit: int = 0
    remaining: int = 0
    reset_seconds: float = 0.0
    last_response_at: float = field(default_factory=time.monotonic)


PERMANENT_4XX = {
    "bad_request", "unauthorized", "forbidden", "not_found", "model_not_found",
    "validation_failed", "task_not_supported_by_model", "payload_too_large",
    "sync_too_large", "unsupported_format", "conflict", "job_expired",
}
RETRYABLE = {
    "too_many_requests",   # 429: rate or concurrency cap
    "model_loading",       # 503: warmup race
    "service_unavailable", # 503: startup/shutdown
}


def _wait_before_next(state: RateLimitState) -> float:
    """Pacing: stay above 20% headroom of the token bucket."""
    if state.limit <= 0:
        return 0.0
    threshold = max(1, int(state.limit * 0.2))
    if state.remaining > threshold:
        return 0.0
    elapsed = time.monotonic() - state.last_response_at
    remaining_window = max(0.0, state.reset_seconds - elapsed)
    if remaining_window <= 0 or state.remaining <= 0:
        return 0.0
    return remaining_window / max(1, state.remaining)


def _read_headers(state: RateLimitState, headers) -> None:
    try:
        state.limit = int(headers.get("RateLimit-Limit", state.limit))
        state.remaining = int(headers.get("RateLimit-Remaining", state.remaining))
        state.reset_seconds = float(headers.get("RateLimit-Reset", state.reset_seconds))
    except (TypeError, ValueError):
        pass
    state.last_response_at = time.monotonic()


def call(
    method: str,
    path: str,
    *,
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
    state: RateLimitState,
    max_attempts: int = 5,
) -> dict:
    """Issue one logical request with retries on retryable errors."""
    url = f"{BASE_URL}{path}"
    base_headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    if headers:
        base_headers.update(headers)

    backoff = 1.0
    for attempt in range(1, max_attempts + 1):
        wait = _wait_before_next(state)
        if wait > 0:
            time.sleep(wait)

        r = requests.request(method, url, json=json_body, headers=base_headers, timeout=120)
        _read_headers(state, r.headers)

        if r.ok:
            return r.json()

        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        err = (body or {}).get("error") or {}
        code = err.get("code", "unknown")

        if code in PERMANENT_4XX:
            # Don't retry; surface to caller.
            raise GIError(r.status_code, code, err.get("message", ""),
                          err.get("request_id"), err.get("details"))

        if code in RETRYABLE and attempt < max_attempts:
            retry_after = r.headers.get("Retry-After")
            sleep = float(retry_after) if retry_after else min(backoff, 30.0)
            time.sleep(sleep)
            backoff *= 2
            continue

        # 5xx server bug — one retry then give up.
        if r.status_code >= 500 and attempt < max_attempts:
            time.sleep(min(backoff, 30.0))
            backoff *= 2
            continue

        raise GIError(r.status_code, code, err.get("message", ""),
                      err.get("request_id"), err.get("details"))

    raise GIError(0, "exhausted", f"max_attempts={max_attempts} reached", None, None)


def demo() -> int:
    if not API_KEY:
        print("ERROR: set GI_API_KEY"); return 2

    state = RateLimitState()
    # A burst of small calls — the wrapper paces automatically.
    for i in range(15):
        try:
            body = call(
                "POST", "/v1/tasks/promoter/predict",
                json_body={"sequence": "ACGT" * 500, "sequence_name": f"demo-{i}",
                           "options": {"threshold": 0.5}},
                state=state,
            )
            ms = body.get("meta", {}).get("inference_time_ms")
            print(f"call {i:>2}: {ms} ms  (limit={state.limit} remaining={state.remaining})")
        except GIError as exc:
            print(f"call {i:>2}: FAILED — {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(demo())
