"""Genomic Intelligence API — partner quickstart.

Hits every public task endpoint with a real, biologically meaningful
sequence drawn from the bundled ``sequences/`` directory (the same
fixtures the service uses for its golden numeric-regression tests).
Sync calls are sized so each task completes in a few seconds on a warm
GPU; ``annotation`` is the one outlier and is intentionally exercised
both sync and async.

    pip install -r requirements.txt
    export GI_API_KEY=gi_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    export GI_BASE_URL=https://api.genomicintelligence.ai   # optional
    python quickstart.py
"""

from __future__ import annotations

import os
import pathlib
import sys

from gi_client import Client, GIError


SEQ_DIR = pathlib.Path(__file__).parent / "sequences"


def load_fasta(filename: str) -> tuple[str, str]:
    """Return (sequence_name, sequence) from a single-record FASTA file."""
    text = (SEQ_DIR / filename).read_text()
    lines = text.splitlines()
    header = lines[0].lstrip(">").strip()
    sequence = "".join(line.strip() for line in lines[1:] if line.strip())
    return header, sequence.upper()


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _summary(label: str, body: dict) -> None:
    meta = body.get("meta", {})
    counts = meta.get("task_specific_counts", {})
    print(
        f"{label:<22} model={meta.get('model'):<32} "
        f"{meta.get('inference_time_ms', '?')} ms  counts={counts}"
    )


def main() -> int:
    api_key = os.environ.get("GI_API_KEY")
    if not api_key:
        print("ERROR: set GI_API_KEY (your gi_… bearer key)", file=sys.stderr)
        return 2
    base_url = os.environ.get("GI_BASE_URL", "https://api.genomicintelligence.ai")

    client = Client(api_key=api_key, base_url=base_url)

    _section("Health")
    print(client.health())

    # All sequences are real biological inputs from the service's golden
    # fixtures — see partner-quickstart/sequences/. Each FASTA carries
    # provenance in its header (gene symbol, coordinates, assembly).
    tp53_name,    tp53_seq    = load_fasta("promoter_tp53.fa")            # human, ~19 kb
    hbb_name,     hbb_seq     = load_fasta("splice_hbb.fa")               # human, ~4 kb
    eve_name,     eve_seq     = load_fasta("enhancer_eve.fa")             # drosophila, ~5 kb
    chr19_name,   chr19_seq   = load_fasta("chromatin_active_promoter_chr19.fa")  # human, ~40 kb
    hbb_tss_name, hbb_tss_seq = load_fasta("expression_hbb_k562.fa")      # human, 9198 bp TSS-centered

    _section("Sync inference (real biological sequences)")
    try:
        _summary("promoter (TP53)",
                 client.predict("promoter",  tp53_seq,  tp53_name))
        _summary("splice   (HBB)",
                 client.predict("splice",    hbb_seq,   hbb_name))
        # Enhancer model is Drosophila-trained — use a fly enhancer.
        _summary("enhancer (eve)",
                 client.predict("enhancer",  eve_seq,   eve_name))
        _summary("chromatin (chr19)",
                 client.predict("chromatin", chr19_seq, chr19_name))
    except GIError as exc:
        print(f"sync task failed: {exc}", file=sys.stderr)
        return 1

    _section("Expression (TSS-centered 9,198 bp window — HBB in K562)")
    # The expression model expects a fixed 9,198 bp window centered on the
    # TSS. The bundled fixture is HBB centered on its canonical TSS; with
    # the K562 cell-type description this should report HIGH expression
    # (HBB is highly expressed in K562 erythroleukemia cells).
    try:
        body = client.predict(
            "expression",
            sequence=hbb_tss_seq,
            sequence_name=hbb_tss_name,
            options={
                "description": (
                    "assay term name is polyA plus RNA-seq. "
                    "biosample summary is Homo sapiens K562."
                ),
            },
        )
        pred = body.get("data", {}).get("prediction", {})
        print(
            f"expression: {pred.get('expression_log_tpm')} log(TPM+1)  "
            f"({pred.get('expression_tpm')} TPM)"
        )
    except GIError as exc:
        print(f"expression failed: {exc}", file=sys.stderr)

    _section("Async job — annotation on TP53 (~19 kbp)")
    # Annotation is the slowest atomic task and the one where async
    # actually matters. TP53 is well-annotated; expect at least one
    # transcript in the response.
    try:
        job_id = client.submit_async(
            "annotation",
            sequence=tp53_seq,
            sequence_name=tp53_name,
            options={"batch_size": 8},
        )
        print(f"submitted job_id={job_id}")

        def progress(p):
            pct = p.get("current_percent")
            msg = p.get("message", "")
            print(f"  {pct:>3}% {msg}")

        body = client.wait_for_job(job_id, poll_interval=2.0, on_progress=progress)
        meta = body.get("meta", {})
        counts = meta.get("task_specific_counts", {})
        transcripts = body.get("data", {}).get("transcripts", []) or []
        print(
            f"done — counts={counts}  "
            f"transcripts={len(transcripts)}  "
            f"total_time_ms={meta.get('inference_time_ms')}"
        )
    except GIError as exc:
        print(f"annotation failed: {exc}", file=sys.stderr)
        return 1

    _section("Recent jobs")
    print(client.list_jobs(limit=5))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
