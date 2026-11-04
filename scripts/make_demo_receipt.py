"""Render the demo receipt: a late-night hackathon dinner, as a hard phone photo.

    uv run python scripts/make_demo_receipt.py samples/midnight-merge.jpg

The bill exercises every hard case at once: a quantity shared unevenly
(3 Red Bulls, "I had two"), a happy-hour discount printed as its own line, tax
and tip to spread, and one item the demo script leaves out so Dex flags it.
The photo is made as hard as a real one: thermal paper on a table, tilted and
in perspective, a hand's shadow across it, small text, a soft focus and heavy
JPEG compression, at the size a messaging app sends.
"""
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

LINES = [
    ("MIDNIGHT MERGE DINER", None),
    ("Open till the build passes", None),
    ("88 Commit St, New Brunswick NJ", None),
    ("11/03/2026  1:47 AM   Table 42", None),
    ("Server: Rubber Duck   Guests: 4", None),
    ("Check #1024", None),
    ("Member 9Q 1129 4471 0083", None),
    ("--------------------------------", None),
    ("1 Merge Conflict Nachos", "14.00"),
    ("  HAPPY HOUR NACHOS", "3.00-"),
    ("1 404 Burger", "15.50"),
    ("1 Stack Overflow Pancakes", "11.00"),
    ("1 Infinite Loop Fries", "6.50"),
    ("3 Red Bull", "12.00"),
    ("1 Null Pointer Noodles", "13.50"),
    ("1 Rubber Duck Sundae", "8.00"),
    ("--------------------------------", None),
    ("SUBTOTAL", "77.50"),
    ("SALES TAX 6.625%", "5.13"),
    ("TIP 18%", "13.95"),
    ("**** TOTAL", "96.58"),
    ("--------------------------------", None),
    ("ITEMS SOLD 10", None),
    ("VISA XXXXXXXXXXXX4417  CHIP", None),
    ("AID A0000000031010  AUTH 05641", None),
    ("APPROVED - Purchase  96.58", None),
    ("|BARCODE|", None),
    ("|BARCODE|", None),
    ("", None),
    ("Suggested tip on 77.50:", None),
    ("18% 13.95  20% 15.50  22% 17.05", None),
    ("", None),
    ("Thanks for shipping!", None),
    ("Come back after the demo", None),
]


def font(size):
    for path in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Courier.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def _row(prefix: str) -> int:
    return next(i for i, (left, _) in enumerate(LINES) if left.startswith(prefix))


def paper() -> Image.Image:
    """The receipt itself: narrow thermal paper, slightly uneven print."""
    rng = random.Random(7)
    f, big = font(15), font(21)
    width, pad, line_h = 380, 24, 22
    img = Image.new("L", (width, pad * 2 + 30 + line_h * len(LINES)), 246)
    d = ImageDraw.Draw(img)
    for i, (left, right) in enumerate(LINES):
        y = pad + i * line_h + (12 if i else 0)
        ink = rng.randint(30, 70)
        if left == "|BARCODE|":
            for x in range(60, width - 60, 3):
                if rng.random() < 0.55:
                    d.rectangle((x, y - 2, x + rng.choice((0, 1, 2)), y + line_h - 2), fill=ink)
            continue
        if right is None:
            ft = big if i == 0 else f
            w = d.textlength(left, font=ft)
            d.text(((width - w) / 2, y - (8 if i == 0 else 0)), left, fill=ink, font=ft)
        else:
            d.text((pad, y), left, fill=ink, font=f)
            w = d.textlength(right, font=f)
            d.text((width - pad - w, y), right, fill=ink, font=f)
    # covered before sharing, like the real receipts: member number, card block, barcode
    for first, last in [(_row("Member"), _row("Member")), (_row("VISA"), _row("APPROVED") + 2)]:
        top, bottom = pad + first * line_h + 8, pad + (last + 1) * line_h + 10
        d.rectangle((40, top, width - 40, bottom), fill=18)
    for _ in range(9000):   # thermal speckle
        x, y = rng.randrange(width), rng.randrange(img.height)
        img.putpixel((x, y), min(255, img.getpixel((x, y)) + rng.randint(-25, 10)))
    return img.convert("RGB")


def photo(path, skew=0.02, tilt=-0.8, blur=0.9, size=(900, 1600), quality=60):
    p = paper()
    # perspective: the top edge further from the camera, so narrower
    w, h = p.size
    k = skew * w
    p = p.transform((w, h), Image.Transform.QUAD, (-k, 0, -k * 0.2, h, w + k * 0.2, h, w + k, 0),
                    Image.Resampling.BICUBIC, fillcolor=(214, 211, 204))
    mask = Image.new("L", p.size, 0)
    ImageDraw.Draw(mask).polygon([(k * 0.9, 0), (k * 0.2, h), (w - k * 0.2, h), (w - k * 0.9, 0)], fill=255)

    table = Image.new("RGB", (int(w * 1.6), int(h * 1.45)), (216, 213, 207))
    noise = Image.effect_noise(table.size, 10).convert("RGB")
    table = Image.blend(table, noise, 0.06)
    table.paste(p, (int(w * 0.26), int(h * 0.2)), mask)
    table = table.rotate(tilt, resample=Image.Resampling.BICUBIC, fillcolor=(216, 213, 207))

    # a hand's shadow across the lower half
    shade = Image.new("L", table.size, 0)
    tw, th = table.size
    ImageDraw.Draw(shade).polygon([(0, th * 0.42), (tw * 0.75, th * 0.47), (tw, th * 0.7), (tw, th), (0, th)], fill=150)
    shade = shade.filter(ImageFilter.GaussianBlur(30))
    table = Image.composite(Image.new("RGB", table.size, (40, 40, 45)), table, shade)

    table = table.filter(ImageFilter.GaussianBlur(blur))
    table.thumbnail(size, Image.Resampling.LANCZOS)
    table.save(path, quality=quality)


if __name__ == "__main__":
    photo(sys.argv[1] if len(sys.argv) > 1 else "samples/midnight-merge.jpg")
