"""Where each item sits on the receipt photo, using SAM 3.1.

SAM 3.1 segments concepts, not text lines: on a receipt, the prompts that
work are "paper" (the receipt itself) and "number" (each printed number). That
is enough. Every priced line ends in a right-aligned amount, so:

1. "number" boxes are grouped into rows by their vertical centre.
2. Rows whose rightmost number sits in the right part of the receipt are the
   priced lines: the items, then subtotal / charges / tax / tip / total.
3. The reader (receipt.py) also reports roughly where each priced line is.
   Those rough positions are matched to SAM's exact rows in order, allowing
   extra rows (a "Table 7" header, a phone number) to go unmatched; a line
   fitted through the matches cancels the reader's drift; then they're
   matched again.

An item that can't be placed confidently is left unlocated rather than drawn
in the wrong place. Boxes are in the photo's own pixels, so the page can draw
them over the image at any size.
"""
import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import httpx

from dex_ai import telemetry

SAM_URL = "https://api.meta.ai/v1/responses"
MODEL = "sam-3.1"
TIMEOUT = 30
RIGHT_EDGE = 0.70        # a price's right edge is past this fraction of the paper's width

_BOX = re.compile(r"<\|box;([^|]*)\|>")


class LocateError(Exception):
    """SAM couldn't be reached or answered badly. The message is user-facing."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def parse_boxes(text: str) -> list[dict]:
    """SAM's output text -> [{x1, y1, x2, y2, w, h, c}] (numbers)."""
    out = []
    for body in _BOX.findall(text):
        fields = dict(kv.split("=", 1) for kv in body.split(";") if "=" in kv)
        try:
            box = {k: float(fields[k]) for k in ("x1", "y1", "x2", "y2", "w", "h")}
        except (KeyError, ValueError):
            continue
        box["c"] = float(fields.get("c", 1))
        out.append(box)
    return out


def segment(image_data_url: str, prompt: str) -> list[dict]:
    """One SAM 3.1 call: noun phrase -> boxes. SAM answers only when streamed."""
    api_key = os.environ.get("MODEL_API_KEY")
    if not api_key:
        raise LocateError("MODEL_API_KEY is not set", status=503)
    payload = {
        "model": MODEL,
        "stream": True,
        "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": image_data_url},
        ]}],
    }
    text = ""
    try:
        with httpx.stream("POST", SAM_URL, json=payload, timeout=TIMEOUT, headers={
            "Authorization": f"Bearer {api_key}", "Accept": "text/event-stream",
        }) as resp:
            if resp.status_code != 200:
                raise LocateError(f"SAM 3.1 returned an error ({resp.status_code})")
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:])
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "response.output_text.delta":
                    text += event.get("delta", "")
    except httpx.TimeoutException:
        raise LocateError("SAM 3.1 took too long", status=504)
    except httpx.HTTPError as e:
        raise LocateError(f"Couldn't reach SAM 3.1: {e}")
    return parse_boxes(text)


def rows(numbers: list[dict]) -> list[dict]:
    """Group number boxes into printed rows, top to bottom."""
    if not numbers:
        return []
    heights = sorted(b["y2"] - b["y1"] for b in numbers)
    tolerance = heights[len(heights) // 2] * 0.9     # a tilted line: qty on the left sits lower than its price
    out: list[dict] = []
    for b in sorted(numbers, key=lambda b: (b["y1"] + b["y2"]) / 2):
        cy = (b["y1"] + b["y2"]) / 2
        if out and abs(cy - out[-1]["cy"]) <= tolerance:
            row = out[-1]
            row["boxes"].append(b)
            row["cy"] = sum((x["y1"] + x["y2"]) / 2 for x in row["boxes"]) / len(row["boxes"])
        else:
            out.append({"cy": cy, "boxes": [b]})
    for row in out:
        bs = row["boxes"]
        row.update(x1=min(b["x1"] for b in bs), y1=min(b["y1"] for b in bs),
                   x2=max(b["x2"] for b in bs), y2=max(b["y2"] for b in bs))
    return out


def priced_rows(all_rows: list[dict], paper: dict) -> list[dict]:
    """Rows that end in a right-aligned amount."""
    edge = paper["x1"] + RIGHT_EDGE * (paper["x2"] - paper["x1"])
    return [r for r in all_rows if r["x2"] >= edge]


def align(predicted: list[float], centres: list[float], skip_cost: float) -> list[int | None]:
    """Match predicted line positions to row centres, in order, at least cost.

    Each prediction takes one row or is skipped (cost `skip_cost`); rows nobody
    takes (a "Table 7" header, a phone number) are free to leave unmatched.
    Returns, per prediction, the index of its row or None.
    """
    n, m = len(predicted), len(centres)
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    move = [[None] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        cost[0][j] = 0.0
    for i in range(1, n + 1):
        cost[i][0] = cost[i - 1][0] + skip_cost
        move[i][0] = "skip"
        for j in range(1, m + 1):
            options = [
                (cost[i][j - 1], "free"),                                        # row j unused
                (cost[i - 1][j] + skip_cost, "skip"),                            # line i unplaced
                (cost[i - 1][j - 1] + abs(centres[j - 1] - predicted[i - 1]), "match"),
            ]
            cost[i][j], move[i][j] = min(options, key=lambda o: o[0])
    out: list[int | None] = [None] * n
    i, j = n, m
    while i > 0:
        step = move[i][j]
        if step == "match":
            out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif step == "skip":
            i -= 1
        else:
            j -= 1
    return out


def fit(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares line actual = a * predicted + b; identity if underdetermined."""
    if len(pairs) < 2:
        return 1.0, (pairs[0][1] - pairs[0][0]) if pairs else 0.0
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return 1.0, my - mx
    a = sum((x - mx) * (y - my) for x, y in pairs) / var
    return a, my - a * mx


def best_match(predicted: list[float], centres: list[float], spacing: float):
    """Align, fit, realign, from many starting guesses; keep the best fit.

    The reader's positions can be off in offset and in scale, so one pass can
    lock onto an answer a whole row out, and a straight-line fit is equally
    happy with that. Each start pins the first predicted line to one row and
    the last to a later row (fixing offset and scale), then aligns, fits and
    realigns. What separates right from wrong is the pattern of gaps (the
    blank line before the subtotal), so each result is scored by how far its
    fitted predictions land from their rows, plus a line's spacing for every
    line left unplaced. Returns (match, adjusted predictions).
    """
    n, m = len(predicted), len(centres)
    starts = [(1.0, 0.0)]
    if n >= 2 and predicted[-1] != predicted[0]:
        span = predicted[-1] - predicted[0]
        for s in range(m):
            for e in range(s + 1, m):
                a = (centres[e] - centres[s]) / span
                if 0.5 <= a <= 2.0:            # a photo isn't squashed or stretched beyond that
                    starts.append((a, centres[s] - a * predicted[0]))
    best = None
    for a0, b0 in starts:
        adjusted = [a0 * p + b0 for p in predicted]
        match = align(adjusted, centres, skip_cost=spacing)
        for _ in range(2):
            a, b = fit([(p, centres[j]) for p, j in zip(predicted, match) if j is not None])
            adjusted = [a * p + b for p in predicted]
            match = align(adjusted, centres, skip_cost=spacing)
        score = sum(abs(centres[j] - p) if j is not None else spacing
                    for p, j in zip(adjusted, match))
        if best is None or score < best[0]:
            best = (score, match, adjusted)
    return best[1], best[2]


def place(receipt: dict, paper: dict, numbers: list[dict]) -> dict:
    """Map the receipt's items to rows on the photo. Pure; testable without SAM.

    The reader gives each priced line a rough position (0–1000 down the image);
    SAM gives exact rows. Predictions are matched to rows in order, a straight
    line is fitted through the matches to cancel the reader's drift, and the
    match is redone (see best_match). Anything still more than half a line off
    is left unplaced.
    """
    priced = priced_rows(rows(numbers), paper)
    items = receipt["items"]
    footer = receipt.get("footer_ys") or []
    h = paper["h"]
    located: dict[int, dict] = {}
    if priced and items and all(i.get("y") is not None for i in items):
        centres = [r["cy"] for r in priced]
        gaps = sorted(b - a for a, b in zip(centres, centres[1:])) or [h / 20]
        spacing = gaps[len(gaps) // 2]
        predicted = [i["y"] * h / 1000 for i in items] + [y * h / 1000 for y in footer]
        match, adjusted = best_match(predicted, centres, spacing)
        left =paper["x1"] + 0.03 * (paper["x2"] - paper["x1"])
        for item, j, p in zip(items, match, adjusted):
            if j is None or abs(centres[j] - p) > spacing / 2:
                continue
            row = priced[j]
            pad = min((row["y2"] - row["y1"]) * 0.2, spacing * 0.08)
            located[item["id"]] = {
                "x1": round(left), "y1": round(row["y1"] - pad),
                "x2": round(row["x2"] + pad), "y2": round(row["y2"] + pad),
            }
    return {
        "width": paper["w"],
        "height": paper["h"],
        "paper": {k: round(paper[k]) for k in ("x1", "y1", "x2", "y2")},
        "items": located,
        "priced_rows": len(priced),
        "expected_rows": len(items) + len(footer),
    }


def locate(receipt: dict, image: bytes, mime: str) -> dict:
    """Receipt photo + its parsed items -> each item's box on the photo."""
    data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    # The two SAM calls are independent; run them side by side.
    with ThreadPoolExecutor(max_workers=2) as pool:
        paper_f = pool.submit(segment, data_url, "paper")
        numbers_f = pool.submit(segment, data_url, "number")
        papers, numbers = paper_f.result(), numbers_f.result()
    if numbers:
        w, h = numbers[0]["w"], numbers[0]["h"]
    elif papers:
        w, h = papers[0]["w"], papers[0]["h"]
    else:
        return {"width": None, "height": None, "paper": None, "items": {},
                "priced_rows": 0, "expected_rows": None}
    paper = max(papers, key=lambda p: (p["x2"] - p["x1"]) * (p["y2"] - p["y1"])) if papers \
        else {"x1": 0, "y1": 0, "x2": w, "y2": h, "w": w, "h": h}
    result = place(receipt, paper, numbers)
    telemetry.note(numbers=len(numbers), priced_rows=result["priced_rows"],
                   expected_rows=result["expected_rows"], located=len(result["items"]))
    return result
