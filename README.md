# Genomic Intelligence — docs

Source for **https://docs.genomicintelligence.ai**. Public-facing
integration kit for the Genomic Intelligence API.

- **Live site:** https://docs.genomicintelligence.ai
- **Live API:** https://api.genomicintelligence.ai
- **Live OpenAPI:** https://api.genomicintelligence.ai/v1/openapi.json
- **Rendered ReDoc:** https://api.genomicintelligence.ai/redoc

## Where to start

- **Agents:** [`AGENTS.md`](AGENTS.md) — structured integration guide.
- **Humans:** [`getting-started.md`](getting-started.md) — auth → sync
  → async walkthrough with curl + Python.
- **Indexed for LLM crawlers:** [`llms.txt`](llms.txt).

## Layout

```
.
├── AGENTS.md          ← agent integration guide (entry point)
├── llms.txt           ← llms.txt convention index
├── partner-brief.md   ← one-page demo-posture summary
├── getting-started.md ← auth → sync → async with curl + Python
├── reference/         ← errors.md, limits.md
├── recipes/           ← runnable .py patterns (1 per intent)
├── snippets/          ← drop-in for partner repos' AGENTS.md
└── client/            ← gi_client.py + quickstart.py + bundled fixtures
```

## Integration kit tarball

```bash
curl -L https://github.com/genomicintelligence/docs/releases/latest/download/integration-kit.tar.gz \
  | tar -xz
cd integration-kit/
```

The tarball ships only the partner-facing content above (no GitHub
Pages plumbing). Built and attached on every published release.

## Contact

alex@genomicintelligence.ai
