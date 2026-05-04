"""Recipe 05 — typed error handling.

Switch on `error.code`, never on `error.message`. Every code from
https://docs.genomicintelligence.ai/reference/errors.md is mapped here
to one of three buckets — retryable / permanent / server-bug — plus
the action your code should take.

Use this as the template for your own error handler. Copy `handle()`
into your codebase, register it as your one place to translate API
errors to your domain's exception types.

    GI_API_KEY=gi_… python3 05_typed_error_handling.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Optional

import requests


BASE_URL = os.environ.get("GI_BASE_URL", "https://api.genomicintelligence.ai")
API_KEY = os.environ.get("GI_API_KEY")


@dataclass
class APIError(Exception):
    status: int
    code: str
    message: str
    request_id: Optional[str]
    details: Any
    bucket: str       # "retryable" | "permanent" | "server_bug" | "proxy_timeout"
    action: str       # human-readable action hint for the caller


def handle(response: requests.Response) -> dict:
    """Convert an API response into either a parsed body or a raised APIError.

    Single source of truth for every code in the catalogue. If we ever add
    a new error code, the `unknown_code` branch surfaces it cleanly.
    """
    if response.ok:
        return response.json()

    # 504 from the edge proxy is the one response on the contract that
    # is NOT the unified error envelope. Treat as a special case.
    if response.status_code == 504:
        raise APIError(
            status=504, code="gateway_timeout",
            message="Upstream proxy read timeout (300 s).",
            request_id=None, details=None,
            bucket="proxy_timeout",
            action="Retry the same request with header `Prefer: respond-async`.",
        )

    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    err = (body or {}).get("error") or {}
    code = err.get("code", "unknown_code")
    msg = err.get("message", "")
    request_id = err.get("request_id")
    details = err.get("details")

    # Retryable transient — the API or upstream is asking you to back off.
    if code == "too_many_requests":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="retryable",
                       action="Honour Retry-After. Both rate-bucket and concurrency 429s use this code.")
    if code == "model_loading":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="retryable",
                       action="Wait ~30 s and retry. The model is warming up.")
    if code == "service_unavailable":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="retryable",
                       action="Backoff and retry. Server is starting up or shutting down.")

    # Permanent client errors — surface to the caller, don't retry.
    if code == "bad_request":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Fix the HTTP-level precondition and re-issue.")
    if code == "unauthorized":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Check Authorization header. WWW-Authenticate splits invalid_request vs invalid_token.")
    if code == "forbidden":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Key is registered but disabled. Contact the API operator.")
    if code == "not_found":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Unknown route, unknown job, or cross-tenant access (returned as 404 not 403).")
    if code == "model_not_found":
        # details.available_models is the typed list of alternatives.
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action=f"Pick a model from details.available_models: {details}.")
    if code == "validation_failed":
        # details.errors is the FastAPI per-field array.
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Surface message verbatim — it's deterministic. See details.errors per-field.")
    if code == "task_not_supported_by_model":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Pick a different model — see details.supported_tasks.")
    if code == "payload_too_large":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Body exceeded 16 MiB. Split the request or use sequence references if available.")
    if code == "sync_too_large":
        # Reserved in the schema; not emitted today but typed for the future.
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Switch to async (`Prefer: respond-async`).")
    if code == "unsupported_format":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="The Accept / ?format= value is not in this task's allowed set.")
    if code == "conflict":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Reserved (e.g. busy-model unload conflict). Retry once after delay.")
    if code == "job_expired":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="permanent",
                       action="Async result evicted (24 h TTL or process restart). Resubmit the original POST.")

    # Server bug — capture and escalate.
    if code == "internal_error":
        raise APIError(response.status_code, code, msg, request_id, details,
                       bucket="server_bug",
                       action=f"Email alex@genomicintelligence.ai with request_id={request_id}.")

    # Unknown code — log loudly so you notice when the catalogue grows.
    raise APIError(response.status_code, code, msg, request_id, details,
                   bucket="server_bug",
                   action=f"Unknown error.code={code!r}. Treat as server bug; capture and escalate.")


def demo() -> int:
    if not API_KEY:
        print("ERROR: set GI_API_KEY"); return 2

    # Trigger 422 validation_failed by sending a non-DNA character.
    print("# trigger validation_failed (422)")
    r = requests.post(
        f"{BASE_URL}/v1/tasks/promoter/predict",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"sequence": "ZZZZ", "sequence_name": "bad-input"},
        timeout=30,
    )
    try:
        handle(r)
    except APIError as exc:
        print(f"  caught: {exc.code} bucket={exc.bucket}")
        print(f"  action: {exc.action}")
        print(f"  message: {exc.message}")

    # Trigger 401 unauthorized with a clearly-bad key.
    print("\n# trigger unauthorized (401)")
    r = requests.get(
        f"{BASE_URL}/v1/tasks/promoter/models",
        headers={"Authorization": "Bearer gi_definitely_not_a_real_key"},
        timeout=10,
    )
    try:
        handle(r)
    except APIError as exc:
        print(f"  caught: {exc.code} bucket={exc.bucket}")
        print(f"  action: {exc.action}")
        print(f"  www-authenticate: {r.headers.get('WWW-Authenticate')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(demo())
