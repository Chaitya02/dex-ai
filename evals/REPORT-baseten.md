# Dex eval report

Run 2026-11-04 11:35 · model `meta-models/muse-spark-open-1026` on `baseten` (reasoning low) · SAM `sam-3.1` · voice `muse-voice-transcribe-1.0`

Regenerate with `uv run python -m evals.run`. Synthetic receipts are seeded, so the set is identical every run; the cases are in `evals/cases.py`.

## Reading receipts (Muse Spark)

| Receipts | Item recall | Item precision | Totals exact | Perfect receipts | p50 | p95 |
|---|---|---|---|---|---|---|
| 13 | 100.0% | 100.0% | 100.0% | 100.0% | 10.36s | 13.54s |

## Placing items on the photo (SAM 3.1)

| Items | Right line | Wrong line | Not placed | p50 | p95 |
|---|---|---|---|---|---|
| 74 | 91.9% | **0.0%** | 8.1% | 2.06s | 3.83s |

Wrong line is the failure that matters: an unplaced item still shows in the list.

## Who had what (assignment agent)

| Cases | Exact split | Items right | Items on wrong people | Items left open | Payer right | p50 | p95 |
|---|---|---|---|---|---|---|---|
| 20 | 90.0% | 100.0% | **0.0%** | 0.0% | 100.0% | 2.31s | 3.34s |

Items on wrong people is the failure that costs money; an item left open shows "Who had this?" on the page.

## Spoken, end to end (voice + agent)

| Cases | Exact split | Items right | Items on wrong people | Items left open | Payer right | p50 | p95 |
|---|---|---|---|---|---|---|---|
| 6 | 83.3% | 100.0% | **0.0%** | 0.0% | 83.3% | 2.31s | 3.19s |

Items on wrong people is the failure that costs money; an item left open shows "Who had this?" on the page.

## Failures

- assign `ambiguous`: wrong [], payer_ok True, tax_tip_ok True, asked_ok False
- assign `ramen-who`: wrong [], payer_ok True, tax_tip_ok True, asked_ok False
- voice `ramen-beers` (Rishi): wrong [], payer_ok False, tax_tip_ok True, asked_ok True · heard: "I had two of the beers and Dwiti had one. I paid."
