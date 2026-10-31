"""Dex's eval suite: run every part against the real models and score it.

    uv run python -m evals.run                     # everything, Meta Model API
    uv run python -m evals.run --only assign       # one part
    uv run python -m evals.run --provider baseten  # Muse Spark Open on Baseten

Four parts, each scored against known answers:

  reading    synthetic receipts (seeded, exact truth) plus any real receipt in
             samples/private/ with a *.truth.json beside it. Item recall and
             precision (name + exact cents), totals exact, receipt perfect.
  placement  the same images through SAM 3.1: items placed on the right line,
             missed, or placed on the WRONG line (the failure that matters).
  assign     who-had-what cases (evals/cases.py): the final split must match
             exactly; ambiguous items must be left unassigned with a question.
  voice      a few cases spoken by macOS voices, transcribed with Muse Voice
             Transcribe, then through the agent: the whole spoken pipeline.

Results go to evals/results/<time>.json, and evals/REPORT.md is rewritten
with the latest numbers. A change to a prompt or model ships only if these
don't get worse.
"""
import argparse
import difflib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from dex_ai import assign, llm, locate, receipt, telemetry, voice  # noqa: E402
from evals import cases as C  # noqa: E402
from evals.synth import generate  # noqa: E402

RESULTS = ROOT / "evals" / "results"
REPORT = ROOT / "evals" / "REPORT.md"
WORKERS = 4
telemetry.log.disabled = True     # the per-request log lines would drown the report


def pct(n, d):
    return None if not d else round(100 * n / d, 1)


def p95(values):
    return telemetry.percentile(values, 95)


def p50(values):
    return telemetry.percentile(values, 50)


# ---------------------------------------------------------------- reading + placement

def receipts(seeds: int) -> list[dict]:
    """[{id, image bytes, mime, truth}] for synthetic seeds and real private receipts."""
    out = []
    for seed in range(1, seeds + 1):
        s = generate(seed)
        buf = io.BytesIO()
        s.image.save(buf, "PNG")
        out.append({"id": f"synth-{seed:02d}", "image": buf.getvalue(), "mime": "image/png",
                    "truth": s.truth, "real": False})
    for truth_file in sorted((ROOT / "samples" / "private").glob("*.truth.json")):
        truth = json.loads(truth_file.read_text())
        image = truth_file.with_name(truth["image"]).read_bytes()
        out.append({"id": f"real-{truth_file.stem.removesuffix('.truth')}", "image": image,
                    "mime": receipt.sniff_image(image), "truth": truth, "real": True})
    return out


def match_items(read: list[dict], truth: list[dict]) -> list[tuple[dict, dict | None]]:
    """Pair each truth item with the read item of the same cents and closest name."""
    free = list(read)
    pairs = []
    for t in truth:
        same = [r for r in free if r["amount_cents"] == t["amount_cents"]]
        best = max(same, key=lambda r: difflib.SequenceMatcher(None, r["name"].lower(), t["name"].lower()).ratio(),
                   default=None)
        if best and difflib.SequenceMatcher(None, best["name"].lower(), t["name"].lower()).ratio() >= 0.6:
            free.remove(best)
            pairs.append((t, best))
        else:
            pairs.append((t, None))
    return pairs


def run_reading(case: dict) -> dict:
    t0 = time.perf_counter()
    try:
        r = receipt.parse(case["image"])
    except Exception as e:
        return {"id": case["id"], "error": f"{type(e).__name__}: {e}"}
    read_s = time.perf_counter() - t0
    truth = case["truth"]
    pairs = match_items(r["items"], truth["items"])
    matched = sum(1 for _, m in pairs if m)
    totals = {k: r.get(k) == truth.get(k) for k in ("subtotal_cents", "tax_cents", "tip_cents", "total_cents")
              if k in truth}
    out = {
        "id": case["id"], "real": case["real"], "read_s": round(read_s, 2),
        "items_truth": len(truth["items"]), "items_read": len(r["items"]), "items_matched": matched,
        "totals_ok": all(totals.values()), "totals": totals,
        "perfect": matched == len(truth["items"]) == len(r["items"]) and all(totals.values()),
        "missing": [t["name"] for t, m in pairs if not m],
        "extra": [x["name"] for x in r["items"] if x not in [m for _, m in pairs]],
    }
    # Placement, on the reader's own output, scored against where the truth's prices are.
    t1 = time.perf_counter()
    try:
        placed = locate.locate(r, case["image"], case["mime"])
    except Exception as e:
        out["placement_error"] = f"{type(e).__name__}: {e}"
        return out
    out["locate_s"] = round(time.perf_counter() - t1, 2)
    half_line = truth["line_height"] / 2
    right = wrong = missed = 0
    for t, m in pairs:
        if not m:
            continue
        box = placed["items"].get(m["id"])
        if not box:
            missed += 1
        elif abs((box["y1"] + box["y2"]) / 2 - t["price_y"]) <= half_line:
            right += 1
        else:
            wrong += 1
    out.update(placed_right=right, placed_wrong=wrong, placed_missed=missed, margin=placed.get("margin"))
    return out


# ---------------------------------------------------------------- assign + voice

def _ratio(weights: dict) -> dict:
    """{person: portion} reduced to lowest terms, so 2:1 == 4:2 == 1.0:0.5."""
    fr = {p: Fraction(str(w)) for p, w in weights.items()}
    low = min(fr.values())
    return {p: w / low for p, w in fr.items()}


def score_assign(case: dict, out: dict) -> dict:
    items = {i["id"]: i["name"] for i in case["receipt"]["items"]}
    got = {items[a["item_id"]]: _ratio(a["weights"]) for a in out["assignments"]}
    want = {name: _ratio(w) for name, w in case["expect"].items()}
    wrong_items = sorted({n for n in set(got) | set(want) if got.get(n) != want.get(n)})
    # Left unassigned when it shouldn't be is a safe miss (the page asks "Who
    # had this?"); assigned to the wrong people is the failure that costs money.
    missed_items = [n for n in wrong_items if n not in got]
    misassigned = [n for n in wrong_items if n in got]
    payer_ok = out["payer"] == case.get("payer", "me")
    tax_ok = out["tax_tip"] == case.get("tax_tip", "proportional")
    asked_ok = all(n not in got for n in case.get("ask", [])) and (not case.get("ask") or bool(out["questions"]))
    return {
        "id": case["id"], "pass": not wrong_items and payer_ok and tax_ok and asked_ok,
        "items_total": len(items), "items_wrong": len(wrong_items), "wrong": wrong_items,
        "items_missed": len(missed_items), "items_misassigned": len(misassigned),
        "payer_ok": payer_ok, "tax_tip_ok": tax_ok, "asked_ok": asked_ok,
        "steps": out["steps"], "stopped": out["stopped"],
        "got": {n: {p: str(w) for p, w in g.items()} for n, g in got.items()},
    }


def run_assign(case: dict, transcript: str | None = None) -> dict:
    current = [{"item_id": next(i["id"] for i in case["receipt"]["items"] if i["name"] == name),
                "weights": weights} for name, weights in case.get("current", {}).items()]
    state = assign.new_state(case["receipt"], case["people"], current, contacts=C.CONTACTS)
    t0 = time.perf_counter()
    try:
        out = assign.run(state, transcript or case["said"], spoken=transcript is not None)
    except Exception as e:
        return {"id": case["id"], "pass": False, "error": f"{type(e).__name__}: {e}"}
    scored = score_assign(case, out)
    scored["agent_s"] = round(time.perf_counter() - t0, 2)
    return scored


def run_voice(case: dict, voice_name: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "said.wav"
        subprocess.run(["say", "-v", voice_name, "-o", str(wav), "--data-format=LEI16@16000", case["said"]],
                       check=True)
        audio = wav.read_bytes()
    # As the page does: people in the split and the receipt's items. Contacts
    # go to the agent, not the recognizer: hinting every contact made it hear
    # "Arya and I each" as "Arya and Aayush".
    hints = list(dict.fromkeys([*case["people"], *(i["name"] for i in case["receipt"]["items"])]))
    t0 = time.perf_counter()
    try:
        heard = voice.transcribe(audio, keywords=hints)["transcript"]
    except Exception as e:
        return {"id": case["id"], "voice": voice_name, "pass": False, "error": f"{type(e).__name__}: {e}"}
    asr_s = time.perf_counter() - t0
    out = run_assign(case, transcript=heard)
    out.update(voice=voice_name, heard=heard, asr_s=round(asr_s, 2))
    return out


# ---------------------------------------------------------------- report

def summarize(results: dict) -> dict:
    s = {}
    if "reading" in results:
        rows = [r for r in results["reading"] if "error" not in r]
        truth_items = sum(r["items_truth"] for r in rows)
        s["reading"] = {
            "receipts": len(results["reading"]), "errors": len(results["reading"]) - len(rows),
            "item_recall": pct(sum(r["items_matched"] for r in rows), truth_items),
            "item_precision": pct(sum(r["items_matched"] for r in rows), sum(r["items_read"] for r in rows)),
            "totals_exact": pct(sum(r["totals_ok"] for r in rows), len(rows)),
            "perfect_receipts": pct(sum(r["perfect"] for r in rows), len(rows)),
            "p50_s": p50([r["read_s"] for r in rows]), "p95_s": p95([r["read_s"] for r in rows]),
        }
        placed = [r for r in rows if "placed_right" in r]
        n = sum(r["placed_right"] + r["placed_wrong"] + r["placed_missed"] for r in placed)
        s["placement"] = {
            "items": n,
            "right": pct(sum(r["placed_right"] for r in placed), n),
            "wrong": pct(sum(r["placed_wrong"] for r in placed), n),
            "missed": pct(sum(r["placed_missed"] for r in placed), n),
            "p50_s": p50([r["locate_s"] for r in placed]), "p95_s": p95([r["locate_s"] for r in placed]),
        }
    for part in ("assign", "voice"):
        if part in results:
            rows = results[part]
            ok = [r for r in rows if "error" not in r]
            s[part] = {
                "cases": len(rows), "pass": pct(sum(r["pass"] for r in rows), len(rows)),
                "item_accuracy": pct(sum(r["items_total"] - r["items_wrong"] for r in ok),
                                     sum(r["items_total"] for r in ok)),
                "misassigned": pct(sum(r["items_misassigned"] for r in ok), sum(r["items_total"] for r in ok)),
                "left_open": pct(sum(r["items_missed"] for r in ok), sum(r["items_total"] for r in ok)),
                "payer_ok": pct(sum(r["payer_ok"] for r in ok), len(ok)),
                "p50_s": p50([r["agent_s"] for r in ok]), "p95_s": p95([r["agent_s"] for r in ok]),
            }
    return s


def write_report(summary: dict, results: dict, meta: dict) -> str:
    lines = [f"# Dex eval report", "",
             f"Run {meta['at']} · model `{meta['model']}` on `{meta['provider']}`"
             f"{' (reasoning ' + meta['effort'] + ')' if meta.get('effort') else ''} · "
             f"SAM `{locate.MODEL}` · voice `{voice.MODEL}`", "",
             "Regenerate with `uv run python -m evals.run`. Synthetic receipts are seeded, so the set is "
             "identical every run; the cases are in `evals/cases.py`.", ""]
    if "reading" in summary:
        r, p = summary["reading"], summary["placement"]
        lines += ["## Reading receipts (Muse Spark)", "",
                  "| Receipts | Item recall | Item precision | Totals exact | Perfect receipts | p50 | p95 |",
                  "|---|---|---|---|---|---|---|",
                  f"| {r['receipts']} | {r['item_recall']}% | {r['item_precision']}% | {r['totals_exact']}% | "
                  f"{r['perfect_receipts']}% | {r['p50_s']}s | {r['p95_s']}s |", "",
                  "## Placing items on the photo (SAM 3.1)", "",
                  "| Items | Right line | Wrong line | Not placed | p50 | p95 |",
                  "|---|---|---|---|---|---|",
                  f"| {p['items']} | {p['right']}% | **{p['wrong']}%** | {p['missed']}% | {p['p50_s']}s | {p['p95_s']}s |",
                  "", "Wrong line is the failure that matters: an unplaced item still shows in the list.", ""]
    for part, title in (("assign", "Who had what (assignment agent)"), ("voice", "Spoken, end to end (voice + agent)")):
        if part in summary:
            a = summary[part]
            lines += [f"## {title}", "",
                      "| Cases | Exact split | Items right | Items on wrong people | Items left open | Payer right | p50 | p95 |",
                      "|---|---|---|---|---|---|---|---|",
                      f"| {a['cases']} | {a['pass']}% | {a['item_accuracy']}% | **{a['misassigned']}%** | "
                      f"{a['left_open']}% | {a['payer_ok']}% | {a['p50_s']}s | {a['p95_s']}s |", "",
                      "Items on wrong people is the failure that costs money; an item left open shows "
                      "\"Who had this?\" on the page.", ""]
    failures = []
    for r in results.get("reading", []):
        if r.get("error") or not r.get("perfect") or r.get("placed_wrong"):
            failures.append(f"- reading `{r['id']}`: " + (r.get("error") or
                            f"missing {r.get('missing')}, extra {r.get('extra')}, totals {r.get('totals')}, "
                            f"placed wrong {r.get('placed_wrong')}, missed {r.get('placed_missed')}"))
    for part in ("assign", "voice"):
        for r in results.get(part, []):
            if not r.get("pass"):
                detail = r.get("error") or (f"wrong {r['wrong']}, payer_ok {r['payer_ok']}, "
                                            f"tax_tip_ok {r['tax_tip_ok']}, asked_ok {r['asked_ok']}")
                heard = f" · heard: \"{r['heard']}\"" if r.get("heard") else ""
                failures.append(f"- {part} `{r['id']}`{' (' + r['voice'] + ')' if r.get('voice') else ''}: {detail}{heard}")
    lines += ["## Failures", "", *(failures or ["None."]), ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="reading,assign,voice", help="comma list of reading,assign,voice")
    ap.add_argument("--seeds", type=int, default=12, help="synthetic receipts to generate")
    ap.add_argument("--provider", help="override DEX_PROVIDER (meta | baseten | fireworks)")
    args = ap.parse_args()
    if args.provider:
        os.environ["DEX_PROVIDER"] = args.provider
    config = llm.config_from_env()
    parts = set(args.only.split(","))
    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        if "reading" in parts:
            results["reading"] = list(pool.map(run_reading, receipts(args.seeds)))
            print(f"reading: {len(results['reading'])} receipts", file=sys.stderr)
        if "assign" in parts:
            results["assign"] = list(pool.map(run_assign, C.CASES))
            print(f"assign: {len(results['assign'])} cases", file=sys.stderr)
        if "voice" in parts:
            by_id = {c["id"]: c for c in C.CASES}
            results["voice"] = list(pool.map(lambda cv: run_voice(by_id[cv[0]], cv[1]), C.VOICE))
            print(f"voice: {len(results['voice'])} cases", file=sys.stderr)
    meta = {"at": time.strftime("%Y-%m-%d %H:%M"), "provider": config.provider, "model": config.model,
            "effort": config.reasoning_effort}
    summary = summarize(results)
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # Real receipts' details stay out of the committed results: ids and scores only.
    (RESULTS / f"{stamp}-{config.provider}.json").write_text(
        json.dumps({"meta": meta, "summary": summary, "results": results}, indent=1, default=str))
    report = write_report(summary, results, meta)
    if set(args.only.split(",")) == {"reading", "assign", "voice"}:
        target = REPORT if config.provider == llm.DEFAULT_PROVIDER else REPORT.with_name(f"REPORT-{config.provider}.md")
        target.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
