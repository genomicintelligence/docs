"""Tiny client for the Genomic Intelligence API.

Wraps `requests` with bearer auth, the unified `{data, meta}` /
`{error}` envelope, and a polling helper for async jobs. Drop this file
into your project and `from gi_client import Client`.

Contract reference: https://api.genomicintelligence.ai/redoc
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests


class GIError(RuntimeError):
    """Raised on any non-2xx response from the API.

    Attributes mirror the unified error envelope so callers can switch
    on ``code`` rather than HTTP status alone:
        {"error": {"code": "...", "message": "...",
                   "request_id": "...", "details": ...}}
    """

    def __init__(self, status: int, body: Dict[str, Any]):
        err = (body or {}).get("error", {}) if isinstance(body, dict) else {}
        self.status = status
        self.code = err.get("code", "http_error")
        self.message = err.get("message", "")
        self.request_id = err.get("request_id")
        self.details = err.get("details")
        super().__init__(
            f"[{status} {self.code}] {self.message} (request_id={self.request_id})"
        )


class Client:
    """Thin synchronous client.

    >>> c = Client(api_key="gi_…")
    >>> r = c.predict("promoter", sequence="ACGT" * 500, sequence_name="demo")
    >>> r["meta"]["inference_time_ms"]
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.genomicintelligence.ai",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------ helpers

    def _check(self, resp: requests.Response) -> Dict[str, Any]:
        try:
            body = resp.json()
        except ValueError:
            body = {"error": {"code": "non_json", "message": resp.text[:200]}}
        if not resp.ok:
            raise GIError(resp.status_code, body)
        return body

    # ----------------------------------------------------------------- requests

    def health(self) -> Dict[str, Any]:
        r = self._session.get(f"{self.base_url}/health", timeout=self.timeout)
        return self._check(r)

    def list_models(self, task: str) -> Dict[str, Any]:
        r = self._session.get(
            f"{self.base_url}/v1/tasks/{task}/models", timeout=self.timeout
        )
        return self._check(r)

    def predict(
        self,
        task: str,
        sequence: str,
        sequence_name: str = "sequence",
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Synchronous prediction. Returns the full ``{data, meta}`` body."""
        body: Dict[str, Any] = {"sequence": sequence, "sequence_name": sequence_name}
        if model is not None:
            body["model"] = model
        if options is not None:
            body["options"] = options
        r = self._session.post(
            f"{self.base_url}/v1/tasks/{task}/predict",
            json=body,
            timeout=self.timeout,
        )
        return self._check(r)

    def submit_async(
        self,
        task: str,
        sequence: str,
        sequence_name: str = "sequence",
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Submit a task in async mode. Returns the ``job_id``."""
        body: Dict[str, Any] = {"sequence": sequence, "sequence_name": sequence_name}
        if model is not None:
            body["model"] = model
        if options is not None:
            body["options"] = options
        r = self._session.post(
            f"{self.base_url}/v1/tasks/{task}/predict",
            headers={"Prefer": "respond-async"},
            json=body,
            timeout=self.timeout,
        )
        body = self._check(r)
        # 202 envelope is {data: {job_id, status, links}, meta: {...}} —
        # uniform with the {data, meta} shape every other successful
        # response on the inference URL produces.
        return body["data"]["job_id"]

    def get_job(self, job_id: str) -> requests.Response:
        """Single poll. The caller inspects ``status_code`` to discriminate."""
        return self._session.get(
            f"{self.base_url}/v1/tasks/jobs/{job_id}", timeout=self.timeout
        )

    def wait_for_job(
        self,
        job_id: str,
        poll_interval: float = 2.0,
        max_wait: float = 30 * 60,
        on_progress=None,
    ) -> Dict[str, Any]:
        """Poll until terminal. Returns ``{data, meta}`` on success, raises ``GIError``."""
        deadline = time.monotonic() + max_wait
        while True:
            r = self.get_job(job_id)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 202:
                if on_progress is not None:
                    try:
                        # 202 poll body is also {data: {progress: {...}}, meta}.
                        on_progress((r.json().get("data") or {}).get("progress") or {})
                    except Exception:
                        pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"job {job_id} did not finish within {max_wait}s")
                time.sleep(poll_interval)
                continue
            # Terminal error
            try:
                body = r.json()
            except ValueError:
                body = {"error": {"code": "non_json", "message": r.text[:200]}}
            raise GIError(r.status_code, body)

    def list_jobs(self, limit: int = 50) -> Dict[str, Any]:
        r = self._session.get(
            f"{self.base_url}/v1/tasks/jobs",
            params={"limit": limit},
            timeout=self.timeout,
        )
        return self._check(r)
