# Dex eval report

Run 2026-10-29 13:04 · model `muse-spark-1.3` on `meta` · SAM `sam-3.1` · voice `muse-voice-transcribe-1.0`

Regenerate with `uv run python -m evals.run`. Synthetic receipts are seeded, so the set is identical every run; the cases are in `evals/cases.py`.

## Reading receipts (Muse Spark)

| Receipts | Item recall | Item precision | Totals exact | Perfect receipts | p50 | p95 |
|---|---|---|---|---|---|---|
| 13 | 100.0% | 100.0% | 100.0% | 100.0% | 9.18s | 11.38s |

## Placing items on the photo (SAM 3.1)

| Items | Right line | Wrong line | Not placed | p50 | p95 |
|---|---|---|---|---|---|
| 74 | 100.0% | **0.0%** | 0.0% | 2.4s | 4.16s |

Wrong line is the failure that matters: an unplaced item still shows in the list.

## Who had what (assignment agent)

| Cases | Exact split | Items right | Items on wrong people | Items left open | Payer right | p50 | p95 |
|---|---|---|---|---|---|---|---|
| 20 | 100.0% | 100.0% | **0.0%** | 0.0% | 100.0% | 3.99s | 7.97s |

Items on wrong people is the failure that costs money; an item left open shows "Who had this?" on the page.

## Spoken, end to end (voice + agent)

| Cases | Exact split | Items right | Items on wrong people | Items left open | Payer right | p50 | p95 |
|---|---|---|---|---|---|---|---|
| 6 | 83.3% | 100.0% | **0.0%** | 0.0% | 83.3% | 3.68s | 5.96s |

Items on wrong people is the failure that costs money; an item left open shows "Who had this?" on the page.

## Failures

- voice `ramen-beers` (Rishi): wrong [], payer_ok False, tax_tip_ok True, asked_ok True · heard: "I had two of the beers and Dwiti had one. I paid."
