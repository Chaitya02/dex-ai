"""Draw docs/workflow.png: Dex's workflow as a plain black-and-white flowchart.

    uv run python scripts/draw_workflow.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2                      # drawn at 2x for a crisp image
W, H = 1000, 1190          # layout units
FONT = "/System/Library/Fonts/HelveticaNeue.ttc"
OUT = Path(__file__).resolve().parent.parent / "docs" / "workflow.png"

img = Image.new("RGB", (W * S, H * S), "white")
d = ImageDraw.Draw(img)


def font(size, bold=False):
    try:
        return ImageFont.truetype(FONT, size * S, index=1 if bold else 0)
    except OSError:
        return ImageFont.load_default(size * S)


TITLE, HEAD, BODY, LABEL = font(30, True), font(17, True), font(14), font(14, True)


def p(*xy):
    return [v * S for v in xy]


def text(cx, cy, lines):
    """Lines centred on (cx, cy); the first is bold."""
    fonts = [HEAD] + [BODY] * (len(lines) - 1)
    heights = [f.size * 1.3 for f in fonts]
    y = cy * S - sum(heights) / 2
    for line, f, h in zip(lines, fonts, heights):
        d.text((cx * S, y + h / 2), line, font=f, fill="black", anchor="mm")
        y += h


def box(cx, cy, w, h, lines, pill=False):
    r = h / 2 if pill else 12
    d.rounded_rectangle(p(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), radius=r * S,
                        outline="black", width=2 * S, fill="white")
    text(cx, cy, lines)


def diamond(cx, cy, w, h, line):
    d.polygon(p(cx, cy - h / 2, cx + w / 2, cy, cx, cy + h / 2, cx - w / 2, cy),
              outline="black", width=2 * S, fill="white")
    d.text((cx * S, cy * S), line, font=HEAD, fill="black", anchor="mm")


def arrow(*pts, label=None, at=None):
    """A line through pts with a head at the last point; label beside segment `at`."""
    d.line(p(*[v for pt in pts for v in pt]), fill="black", width=2 * S, joint="curve")
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    dx, dy = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
    a, b = 11, 6
    d.polygon(p(x1, y1, x1 - dx * a - dy * b, y1 - dy * a + dx * b, x1 - dx * a + dy * b, y1 - dy * a - dx * b),
              fill="black")
    if label:
        (lx, ly) = at
        d.text((lx * S, ly * S), label, font=LABEL, fill="black", anchor="mm")


L, R, C = 290, 710, 500
BW, BH = 300, 74

d.text((C * S, 48 * S), "How Dex Adds a Shared Bill", font=TITLE, fill="black", anchor="mm")

box(L, 125, 220, 50, ["Receipt photo"], pill=True)
box(R, 125, 220, 50, ["Voice or text"], pill=True)

box(L, 237, BW, BH, ["Read the receipt", "Muse Spark Open, strict JSON"])
diamond(L, 345, 230, 100, "Do the sums add up?")
box(88, 345, 150, BH, ["Read again", "more carefully"])
box(L, 467, BW, BH, ["Fold discounts into items", "Costco 13.99 and 4.00- = 9.99"])
box(L, 597, BW, BH, ["Find each price on the photo", "SAM 3.1"])

box(R, 237, BW, BH, ["Transcribe", "Muse Voice Transcribe"])
box(R, 467, BW, BH, ["Decide who had what", "Muse Spark Open, 6 checked tools"])
box(R, 597, BW, BH, ["Split to the cent", "tax and tip by what each had"])

box(C, 737, 340, BH, ["Preview the split", "who owes what, marked on the photo"])
diamond(C, 850, 200, 100, "Looks right?")
box(C, 977, 340, BH, ["Save to Balance Dex", "one expense, exact shares, saved once"])
box(C, 1080, 220, 50, ["Expense log"], pill=True)

arrow((L, 150), (L, 200))
arrow((L, 274), (L, 295))
arrow((L - 115, 345), (163, 345), label="no", at=(172, 324))
arrow((88, 382), (88, 467), (140, 467))
arrow((L, 395), (L, 430), label="yes", at=(L + 24, 412))
arrow((L, 504), (L, 560))

arrow((R, 150), (R, 200))
arrow((R, 274), (R, 430))
arrow((L + BW / 2, 467), (R - BW / 2, 467), label="items", at=(C, 452))
arrow((R, 504), (R, 560))

arrow((L, 634), (L, 667), (440, 667), (440, 700))
arrow((R, 634), (R, 667), (560, 667), (560, 700))
arrow((C, 774), (C, 800))
arrow((C + 100, 850), (930, 850), (930, 467), (R + BW / 2, 467), label="fix it", at=(780, 835))
arrow((C, 900), (C, 940), label="approve", at=(C + 42, 920))
arrow((C, 1014), (C, 1055))

d.text((C * S, 1150 * S), "The models read, listen and decide. The code checks every tool call and does all the math.",
       font=BODY, fill="black", anchor="mm")

img.save(OUT, optimize=True)
print(OUT)
