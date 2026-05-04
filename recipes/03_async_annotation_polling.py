"""Recipe 03 — async annotation with progress polling.

Annotation is the slowest atomic task. For inputs above ~30 kbp, opt
into async to avoid the 300 s upstream proxy timeout. The polling shape
is uniform: HTTP status discriminates progress (`202`) vs terminal
(`200` success, `4xx`/`5xx` failure). Body is always `{data, meta}`
while running and on success; only terminal failure switches to the
error envelope.

Demonstrates:
  - `Prefer: respond-async` opt-in
  - 202-progress polling shape
  - exponential backoff on the poll interval (don't hammer)
  - terminal-state discrimination

    GI_API_KEY=gi_… python3 03_async_annotation_polling.py path/to/sequence.fa
"""

from __future__ import annotations

import os
import sys
import time

import requests


BASE_URL = os.environ.get("GI_BASE_URL", "https://api.genomicintelligence.ai")
API_KEY = os.environ.get("GI_API_KEY")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def load_fasta(path: str) -> tuple[str, str]:
    text = open(path).read().splitlines()
    name = text[0].lstrip(">").strip()
    sequence = "".join(line.strip() for line in text[1:] if line.strip()).upper()
    return name, sequence


def submit_async(sequence: str, sequence_name: str) -> str:
    """POST with `Prefer: respond-async`; return the job_id."""
    r = requests.post(
        f"{BASE_URL}/v1/tasks/annotation/predict",
        headers={**HEADERS, "Prefer": "respond-async"},
        json={"sequence": sequence, "sequence_name": sequence_name,
              "options": {"batch_size": 8}},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["data"]["job_id"]


def poll_until_terminal(job_id: str, max_wait_s: float = 30 * 60) -> dict:
    """Poll `/v1/tasks/jobs/{id}` until 200 or terminal 4xx/5xx.

    Returns the final body. Raises on terminal failure or timeout.
    """
    deadline = time.monotonic() + max_wait_s
    interval = 2.0  # seconds; doubled up to a cap on each 202
    while True:
        r = requests.get(
            f"{BASE_URL}/v1/tasks/jobs/{job_id}",
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()  # done — {data, meta}
        if r.status_code == 202:
            # In flight. Body is also {data, meta}; data.progress carries
            # current_percent / message / elapsed_seconds.
            body = r.json()
            progress = (body.get("data") or {}).get("progress") or {}
            pct = progress.get("current_percent")
            msg = progress.get("message", "")
            print(f"  [{pct:>3}%] {msg}", file=sys.stderr)

            if time.monotonic() > deadline:
                raise TimeoutError(f"job {job_id} did not terminate within {max_wait_s}s")
            time.sleep(interval)
            interval = min(interval * 1.5, 15.0)  # back off, cap at 15s
            continue

        # Terminal failure — unified error envelope.
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        err = body.get("error") or {}
        raise RuntimeError(
            f"job {job_id} terminal: {r.status_code} {err.get('code', 'unknown')} "
            f"{err.get('message', '')} (request_id={err.get('request_id')})"
        )


def main() -> int:
    if not API_KEY:
        print("ERROR: set GI_API_KEY", file=sys.stderr); return 2
    if len(sys.argv) < 2:
        print("usage: 03_async_annotation_polling.py <fasta-path>", file=sys.stderr); return 2

    name, sequence = load_fasta(sys.argv[1])
    print(f"submitting {len(sequence):,} bp as async annotation job…", file=sys.stderr)
    job_id = submit_async(sequence, name)
    print(f"job_id={job_id}", file=sys.stderr)

    body = poll_until_terminal(job_id)
    transcripts = body.get("data", {}).get("transcripts") or []
    meta = body.get("meta", {})
    print(f"done — transcripts={len(transcripts)} "
          f"inference_ms={meta.get('inference_time_ms')} "
          f"counts={meta.get('task_specific_counts')}")
    for t in transcripts:
        print(f"  {t.get('name', '.')}\t{t.get('start')}\t{t.get('end')}\t"
              f"{t.get('strand')}\t{t.get('score'):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
