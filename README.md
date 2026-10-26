# Dex AI

A voice-first, agentic expense companion for students and roommates who share
costs, built on Meta's models for the
[Meta Global AI Developer Hackathon](https://cerebralvalley.ai/e/meta-ai-developer-hackathon)
(Oct 26 – Nov 4, 2026).

**Split it, out loud:** photograph a group bill, say who had what, and Dex
splits it item by item and writes it to Balance Desk once you approve. See
[docs/BUILD_PLAN.md](docs/BUILD_PLAN.md).

| Meta model | Job |
|---|---|
| `muse-spark-1.3` | Reads the receipt photo into line items (vision + JSON schema) |
| `muse-voice-transcribe-1.0` | Transcribes who-had-what, biased toward people's and items' names |
| `sam-3.1` | Item outlines on the receipt (planned) |

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
uv run dex-ai           # app at http://127.0.0.1:8000, API docs at /docs
```

```bash
curl -F image=@samples/luigis.png http://127.0.0.1:8000/api/receipts/parse
curl -F audio=@samples/assign.wav -F keywords=Aayush,Ketan,Kunal http://127.0.0.1:8000/api/voice/transcribe
```

`samples/` holds a synthetic receipt (`scripts/make_sample_receipt.py`) and a
spoken assignment generated with macOS `say`.

Run the tests with `uv run pytest`.

## Model hosts

| `DEX_PROVIDER` | Host | Default model |
|---|---|---|
| `meta` | Meta Model API | `muse-spark-1.3` |
| `baseten` | Baseten | `meta-models/muse-spark-open-1026` |
| `fireworks` | Fireworks | set `DEX_MODEL` |
