# Dex AI

A voice-first, agentic expense companion for students and roommates who share
costs, built on Meta's models for the
[Meta Global AI Developer Hackathon](https://cerebralvalley.ai/e/meta-ai-developer-hackathon)
(Oct 26 – Nov 4, 2026).

Dex captures expenses from speech and receipts, reconciles app balances against
bank data, and proposes fixes that are written only after the user approves them.

## Built during the hackathon

Everything in this repository was written during the hackathon, starting
Oct 26, 2026. Dex connects to [Balance Desk](https://balance-desk.chaityadobariya.me),
my pre-existing, private expense app, over its API; Balance Desk's own code is
not part of this submission.

## Run locally

Requires [uv](https://docs.astral.sh/uv/) and Python 3.14.

```bash
cp .env.example .env    # then set MODEL_API_KEY
uv sync
uv run dex-ai           # http://127.0.0.1:8000/docs
```

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' -d '{"message": "I spent $18 on groceries"}'
```

Run the tests with `uv run pytest`.

## Model hosts

| `DEX_PROVIDER` | Host | Default model |
|---|---|---|
| `meta` | Meta Model API | `muse-spark-1.3` |
| `baseten` | Baseten | `meta-models/muse-spark-open-1026` |
| `fireworks` | Fireworks | set `DEX_MODEL` |
