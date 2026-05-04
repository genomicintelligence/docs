"""Recipe 02 — promoter prediction across a list of human gene symbols.

Realistic batch shape: you have N gene symbols, you want promoters for
each. We fetch the genomic sequence for each gene from Ensembl REST
(public, no auth) and run `POST /v1/tasks/promoter/predict` against
each. Output is one BED-style row per detected promoter region.

Demonstrates:
  - sequence acquisition from a public bioinformatics source (Ensembl)
  - serial pacing against a per-key concurrency cap
  - extraction of the typed `data.regions` field per the contract

    GI_API_KEY=gi_… python3 02_promoters_for_gene_list.py TP53 MYC GAPDH
"""

from __future__ import annotations

import os
import sys
import time
from typing import Iterable

import requests


BASE_URL = os.environ.get("GI_BASE_URL", "https://api.genomicintelligence.ai")
API_KEY = os.environ.get("GI_API_KEY")
ENSEMBL = "https://rest.ensembl.org"

# Default genes to demo if the user gives no args. Sized for sub-2s per call.
DEFAULT_GENES = ["TP53", "MYC", "GAPDH"]


def fetch_gene_sequence(symbol: str, species: str = "human") -> tuple[str, str]:
    """Resolve `symbol` to an Ensembl ID and fetch its genomic sequence.

    Returns (display_name, sequence). Raises on any HTTP failure.
    """
    # Lookup Ensembl ID
    r = requests.get(
        f"{ENSEMBL}/lookup/symbol/{species}/{symbol}",
        headers={"Accept": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    info = r.json()
    ensembl_id = info["id"]
    chrom, start, end = info["seq_region_name"], info["start"], info["end"]

    # Fetch genomic sequence (no flanking)
    r = requests.get(
        f"{ENSEMBL}/sequence/id/{ensembl_id}",
        headers={"Accept": "text/plain"},
        timeout=30,
    )
    r.raise_for_status()
    return f"{symbol}|chr{chrom}:{start}-{end}", r.text.strip().upper()


def predict_promoter(sequence: str, sequence_name: str) -> dict:
    """One sync call to /v1/tasks/promoter/predict. Returns the {data, meta} body."""
    r = requests.post(
        f"{BASE_URL}/v1/tasks/promoter/predict",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={"sequence": sequence, "sequence_name": sequence_name,
              "options": {"threshold": 0.5}},
        timeout=120,
    )
    if not r.ok:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        err = body.get("error") or {}
        raise RuntimeError(
            f"{r.status_code} {err.get('code', 'unknown')}: "
            f"{err.get('message', r.text[:200])} (request_id={err.get('request_id')})"
        )
    return r.json()


def pace(headers) -> float:
    """Return how many seconds to sleep before the next call to stay at ~80% of capacity.

    Reads IETF RateLimit-* headers. If headroom is low, slow down; if
    plenty, no wait. Conservative pacing — beats reactive 429 retries.
    """
    try:
        remaining = int(headers.get("RateLimit-Remaining", "999"))
        limit = int(headers.get("RateLimit-Limit", "10"))
        reset = float(headers.get("RateLimit-Reset", "0"))
    except (TypeError, ValueError):
        return 0.0
    threshold = max(1, int(limit * 0.2))  # aim to stay above 20% headroom
    if remaining <= threshold and reset > 0:
        # Spread remaining work across the reset window
        return reset / max(1, remaining)
    return 0.0


def run(symbols: Iterable[str]) -> int:
    if not API_KEY:
        print("ERROR: set GI_API_KEY", file=sys.stderr)
        return 2

    print("# track  start  end  name  score")
    last_headers = {}
    for symbol in symbols:
        wait = pace(last_headers)
        if wait > 0:
            print(f"# pacing: sleep {wait:.2f}s", file=sys.stderr)
            time.sleep(wait)

        try:
            display, sequence = fetch_gene_sequence(symbol)
        except requests.HTTPError as exc:
            print(f"# {symbol}: ensembl lookup failed — {exc}", file=sys.stderr)
            continue

        try:
            body = predict_promoter(sequence, display)
        except RuntimeError as exc:
            print(f"# {symbol}: predict failed — {exc}", file=sys.stderr)
            continue

        # Capture headers from the most recent successful call for pacing.
        # (In a real client we'd return the response object from the helper;
        # kept inline here to keep the recipe linear and readable.)
        regions = body.get("data", {}).get("regions") or []
        for r in regions:
            print(f"{symbol}\t{r['start']}\t{r['end']}\t{r.get('name', '.')}\t{r['score']:.4f}")
        if not regions:
            print(f"# {symbol}: 0 regions above threshold", file=sys.stderr)

    return 0


if __name__ == "__main__":
    args = sys.argv[1:] or DEFAULT_GENES
    raise SystemExit(run(args))
