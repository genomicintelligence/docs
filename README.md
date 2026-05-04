# Genomic Intelligence API — docs

REST API for DNA sequence analysis with transformer language models.
Six tasks — **promoter, splice site, enhancer, chromatin, expression,
annotation** — over a typed `/v1` contract.

## Where to start

- **Humans:** [`getting-started.md`](getting-started.md) — auth → sync
  → async walkthrough with curl + Python.
- **Agents:** [`AGENTS.md`](AGENTS.md) — structured integration guide
  for agentic systems.
- **One-page summary:** [`partner-brief.md`](partner-brief.md) — what
  this is, what it isn't, your key, expected latency.
- **Indexed for LLM crawlers:** [`llms.txt`](llms.txt).

## Live URLs

- API: <https://api.genomicintelligence.ai>
- OpenAPI schema: <https://api.genomicintelligence.ai/v1/openapi.json>
- Rendered API reference (ReDoc): <https://api.genomicintelligence.ai/redoc>

## Integration kit tarball

```bash
curl -L https://github.com/genomicintelligence/docs/releases/latest/download/integration-kit.tar.gz | tar -xz
cd integration-kit/
```

The tarball ships only the partner-facing content (no GitHub Pages
plumbing). Built and attached on every published release.

## Layout

```
.
├── AGENTS.md          ← agent integration guide
├── llms.txt           ← llms.txt convention index
├── partner-brief.md   ← one-page demo-posture summary
├── getting-started.md ← auth → sync → async with curl + Python
├── reference/         ← errors.md, limits.md
├── recipes/           ← runnable .py patterns (1 per intent)
├── snippets/          ← drop-in for partner repos' AGENTS.md
└── client/            ← gi_client.py + quickstart.py + bundled fixtures
```

## Contact

alex@genomicintelligence.ai
