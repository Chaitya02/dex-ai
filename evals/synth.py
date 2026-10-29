"""Synthetic receipts with exact ground truth, for the eval set.

Each receipt is generated from a seed, so the set is the same on every run:
merchant, 2–10 items (some with quantities, some discounts), optional service
fee, tax, optional tip, header lines that contain numbers (table, phone,
store number), payment lines below the total, a small tilt and a choice of
font size. The truth records every item's name and cents, the totals, and
where each item's price sits on the image (after the tilt), so reading,
splitting and placement can all be scored.
"""
import math
import random
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

MERCHANTS = ["Luigi's Trattoria", "Sakura Ramen House", "The Daily Grind", "Bombay Spice",
             "Brick Oven Co", "Taqueria El Sol", "Golden Dragon", "Harvest Market",
             "Corner Deli", "Pho Saigon", "Burger Barn", "Seoul Kitchen"]
DISHES = ["Margherita Pizza", "Penne alla Vodka", "Chicken Parm", "Garlic Knots", "Caesar Salad",
          "Tonkotsu Ramen", "Gyoza", "Edamame", "Iced Latte", "Cappuccino", "Blueberry Muffin",
          "Butter Chicken", "Garlic Naan", "Mango Lassi", "Paneer Tikka", "Carnitas Taco",
          "Chips & Salsa", "Horchata", "Kung Pao Chicken", "Fried Rice", "Spring Rolls",
          "Pho Tai", "Banh Mi", "Thai Iced Tea", "Bacon Burger", "Sweet Potato Fries",
          "Bibimbap", "Kimchi Pancake", "Fountain Soda", "Tiramisu", "Cheesecake", "Lemonade"]
FONTS = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Courier.ttc"]


@dataclass
class Synth:
    seed: int
    image: Image.Image
    truth: dict = field(default_factory=dict)


def _font(size, which):
    for path in [FONTS[which % len(FONTS)], *FONTS]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def money(cents):
    return f"{'-' if cents < 0 else ''}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def generate(seed: int) -> Synth:
    rng = random.Random(seed)
    merchant = rng.choice(MERCHANTS)
    n = rng.randint(2, 10)
    items = []
    for name in rng.sample(DISHES, n):
        qty = rng.choice([1, 1, 1, 2, 3])
        unit = rng.randint(250, 2400)
        items.append({"name": name, "quantity": qty, "cents": unit * qty})
    if rng.random() < 0.2:
        items.append({"name": "Coupon", "quantity": 1, "cents": -rng.choice([200, 300, 500])})
    subtotal = sum(i["cents"] for i in items)
    fee = rng.choice([0, 0, 0, 150, 250])
    tax = round(subtotal * rng.choice([0, 0.06625, 0.08875, 0.07]))
    tip = rng.choice([0, 0, round(subtotal * 0.18), round(subtotal * 0.2)])
    total = subtotal + fee + tax + tip
    date = f"2026-10-{rng.randint(10, 27):02d}"

    lines = [(merchant.upper(), None, "center"),
             (f"Store #{rng.randint(10, 999)}  Tel 732-{rng.randint(200, 999)}-{rng.randint(1000, 9999)}", None, "center"),
             (f"{date[5:7]}/{date[8:]}/2026  {rng.randint(11, 21)}:{rng.randint(10, 59)}   Table {rng.randint(1, 30)}", None, "center"),
             ("", None, None)]
    for i in items:
        label = f"{i['quantity']} {i['name']}" if rng.random() < 0.7 else i["name"]
        lines.append((label, money(i["cents"]), "item"))
    lines.append(("", None, None))
    lines.append(("SUBTOTAL", money(subtotal), "other"))
    if fee:
        lines.append(("SERVICE FEE", money(fee), "other"))
    if tax:
        lines.append(("TAX", money(tax), "other"))
    if tip:
        lines.append(("TIP", money(tip), "other"))
    lines.append(("TOTAL", money(total), "other"))
    lines.append(("", None, None))
    lines.append((f"VISA ****{rng.randint(1000, 9999)}", money(total), "other"))
    lines.append(("Thank you!", None, "center"))

    size = rng.choice([22, 26, 30])
    f = _font(size, rng.randint(0, 1))
    line_h = int(size * 1.5)
    width, pad = 620, 36
    img = Image.new("RGB", (width, pad * 2 + line_h * len(lines)), "#fbfaf6")
    draw = ImageDraw.Draw(img)
    price_points = []    # (x of price's right end, y centre) per item, before tilt
    for k, (left, right, kind) in enumerate(lines):
        y = pad + k * line_h
        if kind == "center":
            w = draw.textlength(left, font=f)
            draw.text(((width - w) / 2, y), left, fill="#222", font=f)
            continue
        if not left:
            continue
        draw.text((pad, y), left, fill="#222", font=f)
        w = draw.textlength(right, font=f)
        draw.text((width - pad - w, y), right, fill="#222", font=f)
        if kind == "item":
            price_points.append((width - pad, y + size * 0.6))

    angle = rng.uniform(-2.5, 2.5)
    cx, cy = img.width / 2, img.height / 2
    img = img.rotate(angle, center=(cx, cy), fillcolor="#d9d4c7")
    t = math.radians(angle)

    def rotated(x, y):
        # PIL rotates counter-clockwise on screen (y grows downward).
        dx, dy = x - cx, y - cy
        return cx + dx * math.cos(t) + dy * math.sin(t), cy - dx * math.sin(t) + dy * math.cos(t)

    truth = {
        "merchant": merchant,
        "date": date,
        "items": [{"id": k + 1, "name": i["name"], "quantity": i["quantity"], "amount_cents": i["cents"],
                   "price_y": round(rotated(*p)[1], 1)}
                  for k, (i, p) in enumerate(zip(items, price_points))],
        "subtotal_cents": subtotal,
        "fee_cents": fee,
        "tax_cents": tax or None,
        "tip_cents": tip or None,
        "total_cents": total,
        "line_height": line_h,
        "angle": round(angle, 2),
    }
    return Synth(seed, img, truth)
