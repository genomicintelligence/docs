"""Recipe 01 — health probe.

The minimum check before any other work: is the API reachable, is your
key valid, are the per-task model lists loadable. Exits 0 on green, 1
on any failure.

    GI_API_KEY=gi_… python3 01_health_probe.py
"""

from __future__ import annotations

import os
import sys

import requests


BASE_URL = os.environ.get("GI_BASE_URL", "https://api.genomicintelligence.ai")
API_KEY = os.environ.get("GI_API_KEY")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    if not API_KEY:
        fail("set GI_API_KEY")

    # 1. Public liveness — no auth required.
    r = requests.get(f"{BASE_URL}/health", timeout=10)
    if not r.ok:
        fail(f"/health returned {r.status_code}: {r.text[:200]}")
    health = r.json()
    print(f"health   : {health.get('status')} {health.get('version')}")

    # 2. Authenticated round-trip — proves the bearer key is registered.
    r = requests.get(
        f"{BASE_URL}/v1/tasks/promoter/models",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=10,
    )
    if r.status_code == 401:
        fail("401 unauthorized — key missing, malformed, or unrecognised. "
             f"Check Authorization header. Body: {r.text[:200]}")
    if not r.ok:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        err = body.get("error") or {}
        fail(f"{r.status_code} {err.get('code', 'unknown')} request_id={err.get('request_id')}")
    # Note: model-listing endpoints (`/v1/tasks/{task}/models`,
    # `/v1/tasks/{task}/models/{id}/status`) return flat objects, NOT the
    # `{data, meta}` envelope used by predict endpoints. Live OpenAPI at
    # /v1/openapi.json is the source of truth for shapes per route.
    body = r.json()
    models = body.get("models", [])
    print(f"models   : {len(models)} registered for task=promoter "
          f"(default={body.get('default_model')})")

    # 3. Read RateLimit headers — confirms your tier and your headroom.
    print(f"ratelimit: limit={r.headers.get('RateLimit-Limit')} "
          f"remaining={r.headers.get('RateLimit-Remaining')} "
          f"reset={r.headers.get('RateLimit-Reset')}s "
          f"policy={r.headers.get('RateLimit-Policy')}")

    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
