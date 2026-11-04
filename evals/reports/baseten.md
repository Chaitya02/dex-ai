# Dex eval report

Run 2026-11-04 11:44 · model `meta-models/muse-spark-open-1026` on `baseten` (reasoning low) · SAM `sam-3.1` · voice `muse-voice-transcribe-1.0`

Regenerate with `uv run python -m evals.run`. Synthetic receipts are seeded, so the set is identical every run; the cases are in `evals/cases.py`.

## Reading receipts (Muse Spark)

| Receipts | Item recall | Item precision | Totals exact | Perfect receipts | p50 | p95 |
|---|---|---|---|---|---|---|
| 15 | 100.0% | 100.0% | 100.0% | 100.0% | 10.76s | 15.19s |

### Real bills from the hackathon week

| Bill | Read exactly | Items right | Time |
|---|---|---|---|
| ajisen | yes | 5/5 | 11.98s |
| aldi | yes | 4/4 | 10.0s |
| costco | yes | 31/31 | 15.19s |

## Placing items on the photo (SAM 3.1)

| Items | Right line | Wrong line | Not placed | p50 | p95 |
|---|---|---|---|---|---|
| 74 | 82.4% | **0.0%** | 17.6% | 3.24s | 6.09s |

Wrong line is the failure that matters: an unplaced item still shows in the list.

### Who had what, on the real bills

| Case | Exact split | Items right |
|---|---|---|
| ajisen-dinner | yes | 5/5 |
| ajisen-fix | yes | 5/5 |
| costco-roommates | yes | 31/31 |

## Who had what (assignment agent)

| Cases | Exact split | Items right | Items on wrong people | Items left open | Payer right | p50 | p95 |
|---|---|---|---|---|---|---|---|
| 23 | 95.7% | 100.0% | **0.0%** | 0.0% | 100.0% | 2.27s | 3.51s |

Items on wrong people is the failure that costs money; an item left open shows "Who had this?" on the page.

## Spoken, end to end (voice + agent)

| Cases | Exact split | Items right | Items on wrong people | Items left open | Payer right | p50 | p95 |
|---|---|---|---|---|---|---|---|
| 6 | 83.3% | 100.0% | **0.0%** | 0.0% | 83.3% | 2.11s | 2.78s |

Items on wrong people is the failure that costs money; an item left open shows "Who had this?" on the page.

## Failures

- assign `ramen-who`: wrong [], payer_ok True, tax_tip_ok True, asked_ok False
- voice `ramen-beers` (Rishi): wrong [], payer_ok False, tax_tip_ok True, asked_ok True · heard: "i had two of the beers and Dwiti had one. i paid."
