# Dex eval report

Run 2026-10-31 00:14 · model `meta-models/muse-spark-open-1026` on `baseten` (reasoning low) · SAM `sam-3.1` · voice `muse-voice-transcribe-1.0`

Regenerate with `uv run python -m evals.run`. Synthetic receipts are seeded, so the set is identical every run; the cases are in `evals/cases.py`.

## Reading receipts (Muse Spark)

| Receipts | Item recall | Item precision | Totals exact | Perfect receipts | p50 | p95 |
|---|---|---|---|---|---|---|
| 13 | 100.0% | 100.0% | 100.0% | 100.0% | 6.74s | 10.11s |

## Placing items on the photo (SAM 3.1)

| Items | Right line | Wrong line | Not placed | p50 | p95 |
|---|---|---|---|---|---|
| 74 | 91.9% | **0.0%** | 8.1% | 1.77s | 3.26s |

Wrong line is the failure that matters: an unplaced item still shows in the list.

## Who had what (assignment agent)

| Cases | Exact split | Items right | Items on wrong people | Items left open | Payer right | p50 | p95 |
|---|---|---|---|---|---|---|---|
| 20 | 95.0% | 100.0% | **0.0%** | 0.0% | 100.0% | 2.26s | 3.94s |

Items on wrong people is the failure that costs money; an item left open shows "Who had this?" on the page.

## Spoken, end to end (voice + agent)

| Cases | Exact split | Items right | Items on wrong people | Items left open | Payer right | p50 | p95 |
|---|---|---|---|---|---|---|---|
| 6 | 66.7% | 86.1% | **0.0%** | 13.9% | 83.3% | 2.21s | 3.94s |

Items on wrong people is the failure that costs money; an item left open shows "Who had this?" on the page.

## Failures

- assign `ramen-who`: wrong [], payer_ok True, tax_tip_ok True, asked_ok False
- voice `ramen-basic` (Samantha): wrong ['Edamame', 'Gyoza', 'Matcha Ice Cream', 'Spicy Miso Ramen', 'Tonkotsu Ramen'], payer_ok True, tax_tip_ok True, asked_ok True · heard: "Arya and Aich had a tonkotsu, Dwiti had the spicy miso, we all shared the gyoza and edamame, Arya and Dwiti had the ice cream."
- voice `ramen-beers` (Rishi): wrong [], payer_ok False, tax_tip_ok True, asked_ok True · heard: "i had two of the beers and Dwiti had one. i paid."
