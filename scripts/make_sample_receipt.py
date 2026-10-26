"""Render a synthetic restaurant receipt for testing the reader.

    uv run python scripts/make_sample_receipt.py samples/luigis.png
"""
import sys

from PIL import Image, ImageDraw, ImageFont

LINES = [
    ("LUIGI'S TRATTORIA", None),
    ("112 Easton Ave, New Brunswick NJ", None),
    ("10/24/2026  8:14 PM   Table 7", None),
    ("", None),
    ("1 Margherita Pizza", "18.50"),
    ("1 Penne alla Vodka", "16.00"),
    ("1 Chicken Parm", "21.00"),
    ("2 Garlic Knots", "9.00"),
    ("3 Fountain Soda", "8.25"),
    ("1 Tiramisu", "7.50"),
    ("", None),
    ("SUBTOTAL", "80.25"),
    ("SALES TAX 6.625%", "5.32"),
    ("TIP", "16.00"),
    ("TOTAL", "101.57"),
    ("", None),
    ("VISA ****4417", None),
    ("Thank you! Grazie!", None),
]


def font(size):
    for path in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Courier.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def render(path):
    f = font(28)
    width, pad, line_h = 620, 40, 42
    img = Image.new("RGB", (width, pad * 2 + line_h * len(LINES)), "#fbfaf6")
    draw = ImageDraw.Draw(img)
    for i, (left, right) in enumerate(LINES):
        y = pad + i * line_h
        if right is None:
            w = draw.textlength(left, font=f)
            draw.text(((width - w) / 2, y), left, fill="#222", font=f)
        else:
            draw.text((pad, y), left, fill="#222", font=f)
            w = draw.textlength(right, font=f)
            draw.text((width - pad - w, y), right, fill="#222", font=f)
    img.rotate(1.5, expand=True, fillcolor="#d9d4c7").save(path)


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else "samples/luigis.png")
