"""Draw docs/workflow.png: Dex's workflow as a plain black-and-white flowchart.

    uv run python scripts/draw_workflow.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2                      # drawn at 2x for a crisp image
W, H = 1000, 1325          # layout units
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


L, R, C = 340, 710, 500
BW, BH = 300, 74
X = 95                     # the re-read column, left of the receipt path

d.text((C * S, 48 * S), "How Dex Adds a Shared Bill", font=TITLE, fill="black", anchor="mm")

box(L, 125, 220, 50, ["Receipt photo"], pill=True)
box(R, 125, 220, 50, ["Voice or text"], pill=True)

box(L, 237, BW, BH, ["Read the receipt", "Muse Spark Open, strict JSON"])
diamond(L, 345, 230, 100, "Do the sums add up?")
box(X, 345, 150, BH, ["Read again", "more carefully"])
diamond(X, 470, 170, 90, "Adds up now?")
box(X, 600, 150, BH, ["Flag it", "which sum is off"])
box(L, 600, BW, BH, ["Fold discounts into items", "a savings line joins its item"])
box(L, 730, BW, BH, ["Find each price on the photo", "SAM 3.1"])

box(R, 237, BW, BH, ["Transcribe", "Muse Voice Transcribe"])
box(R, 600, BW, BH, ["Decide who had what", "Muse Spark Open, 6 checked tools"])
box(R, 730, BW, BH, ["Split to the cent", "tax and tip by what each had"])

box(C, 870, 340, BH, ["Preview the split", "who owes what, marked on the photo"])
diamond(C, 983, 200, 100, "Looks right?")
box(C, 1110, 340, BH, ["Save to Balance Dex", "one expense, exact shares, saved once"])
box(C, 1210, 220, 50, ["Expense log"], pill=True)

arrow((L, 150), (L, 200))
arrow((L, 274), (L, 295))
arrow((L - 115, 345), (X + 75, 345), label="no", at=(X + 97, 324))
arrow((X, 382), (X, 425))
arrow((X + 85, 470), (L, 470), label="yes", at=(X + 108, 455))
arrow((X, 515), (X, 563), label="no", at=(X + 18, 538))
arrow((X + 75, 600), (L - BW / 2, 600))
arrow((L, 395), (L, 563), label="yes", at=(L + 24, 415))
arrow((L, 637), (L, 693))

arrow((R, 150), (R, 200))
arrow((R, 274), (R, 563))
arrow((L + BW / 2, 600), (R - BW / 2, 600), label="items", at=((L + R) / 2, 585))
arrow((R, 637), (R, 693))

arrow((L, 767), (L, 800), (440, 800), (440, 833))
arrow((R, 767), (R, 800), (560, 800), (560, 833))
arrow((C, 907), (C, 933))
arrow((C + 100, 983), (930, 983), (930, 600), (R + BW / 2, 600), label="fix it", at=(780, 968))
arrow((C, 1033), (C, 1073), label="approve", at=(C + 42, 1053))
arrow((C, 1147), (C, 1185))

d.text((C * S, 1285 * S), "The models read, listen and decide. The code checks every tool call and does all the math.",
       font=BODY, fill="black", anchor="mm")

img.save(OUT, optimize=True)
print(OUT)
