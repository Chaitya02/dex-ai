# Build plan: "Split it, out loud"

Photograph a group bill, say who had what, and Dex splits it item by item,
shows the split on the receipt, and writes it to Balance Desk once you approve.

## The flow

1. **Capture**: take or upload a photo of the receipt.
2. **Read**: Muse Spark extracts merchant, line items, tax, tip and total as
   structured JSON. Code checks the arithmetic (items vs. subtotal, subtotal +
   tax + tip vs. total) and flags anything that doesn't add up.
3. **Locate**: SAM 3.1 outlines each line item on the photo so the user can see
   what was read.
4. **Assign**: the user speaks ("I had the pasta, Aayush and Ketan split the
   pizza, everyone shared the fries, Kunal paid"). Muse Voice Transcribe turns it
   into text, with the receipt's item names and the user's contacts as
   vocabulary hints.
5. **Split**: a Muse Spark agent maps people to items through tools. Code (not
   the model) computes each share, and spreads tax and tip in proportion,
   to the cent.
6. **Propose**: the split is drawn on the receipt, each item tagged by person.
   Voice corrections ("Aayush didn't have fries") update it.
7. **Approve and write**: on approval, the expenses and contact balances are
   created in Balance Desk through a token-protected API.

## Meta models used

| Model | Job |
|---|---|
| `muse-spark-1.3` | Receipt reading (vision + JSON schema), the assignment agent |
| `muse-voice-transcribe-1.0` | Spoken assignments and corrections |
| `sam-3.1` | Item outlines on the receipt photo |
| Muse Spark Open (Baseten) | Same receipt and agent path on open weights, for the open-weight bonus |

## Schedule

| Day | Date | Deliverable |
|---|---|---|
| 1 | Mon Oct 26 – Tue Oct 27 | Receipt reading endpoint, voice transcription endpoint, capture page (photo + mic) |
| 2 | Wed Oct 28 | Split engine: item assignments to per-person shares, proportional tax/tip, cent rounding; tests |
| 3 | Thu Oct 29 | Assignment agent: transcript + receipt to assignments via tools; contacts as vocabulary |
| 4 | Fri Oct 30 | Proposal view on the receipt; voice corrections loop |
| 5 | Sat Oct 31 | SAM 3.1 item outlines; tagged overlay |
| 6 | Sun Nov 1 | Balance Desk write API (token auth) and approve-and-write |
| 7 | Mon Nov 2 | Eval set: receipts + spoken assignments with known correct splits; accuracy report |
| 8 | Tue Nov 3 | Muse Spark Open path on Baseten; polish; deploy |
| 9 | Wed Nov 4 | Demo video (opens with what was pre-existing), README, X post, submit by 9 PM ET |

Stretch, only if ahead: hands-free voice commands for everyday adds and edits;
proactive "split this with the usual three?" when a bank charge arrives.

## What judges should see as new

Everything in this repository. Balance Desk (the expense app, its text-chat Dex
agent and its nightly reconciliation) existed before the event; the only change
to it during the event is the small write API Dex calls in step 7.

## Rules to keep in mind

- Public repo, new work only, demo shows only what was built during the event.
- Meta models must be a real part of what runs (Stage 1 check).
- Submit by Wed Nov 4, 9:00 PM ET with a 3-minute video.
