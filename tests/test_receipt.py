import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dex_ai import llm, receipt
from dex_ai.app import app

client = TestClient(app)

RAW = {
    "merchant": "Luigi's",
    "date": "2026-10-24",
    "currency": "USD",
    "items": [
        {"name": "Margherita Pizza", "quantity": 1, "amount": 18.5},
        {"name": "Penne Vodka", "quantity": 1, "amount": 16.0},
        {"name": "Fries", "quantity": 2, "amount": 9.0},
        {"name": "Coupon", "quantity": 1, "amount": -3.0},
    ],
    "subtotal": 40.5,
    "tax": 3.59,
    "tip": 8.1,
    "other_charges": [{"name": "Service fee", "amount": 1.0}],
    "total": 53.19,
}


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "PNG")
    return buf.getvalue()


def test_to_cents_rounds_half_up():
    assert receipt.to_cents(0.1 + 0.2) == 30
    assert receipt.to_cents(2.675) == 268
    assert receipt.to_cents(None) is None


def test_normalize_converts_to_cents_and_passes_checks():
    r = receipt.normalize(RAW)
    assert [i["amount_cents"] for i in r["items"]] == [1850, 1600, 900, -300]
    assert [i["id"] for i in r["items"]] == [1, 2, 3, 4]
    assert r["total_cents"] == 5319
    assert all(c["ok"] for c in r["checks"])


def test_checks_flag_mismatch_without_fixing():
    r = receipt.normalize({**RAW, "total": 54.19})
    total = next(c for c in r["checks"] if c["check"] == "total")
    assert not total["ok"]
    assert "off by +1.00" in total["message"]
    assert r["total_cents"] == 5419


def test_no_items_is_a_failed_check():
    r = receipt.normalize({**RAW, "items": []})
    assert r["checks"] == [{"ok": False, "check": "items", "message": "No line items found"}]


def test_sniff_rejects_non_images():
    with pytest.raises(receipt.ReceiptError):
        receipt.sniff_image(b"%PDF-1.7 not an image")
    assert receipt.sniff_image(png_bytes()) == "image/png"


def test_parse_sends_image_and_schema(monkeypatch):
    seen = {}

    def fake_chat(messages, config=None, **kwargs):
        seen["messages"], seen["kwargs"] = messages, kwargs
        return json.dumps(RAW)

    monkeypatch.setattr(llm, "chat", fake_chat)
    r = receipt.parse(png_bytes())
    image_part = seen["messages"][0]["content"][1]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert seen["kwargs"]["response_format"]["type"] == "json_schema"
    assert r["merchant"] == "Luigi's"


def test_parse_endpoint(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: json.dumps(RAW))
    resp = client.post("/api/receipts/parse", files={"image": ("r.png", png_bytes(), "image/png")})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 4


def test_parse_endpoint_rejects_bad_upload():
    resp = client.post("/api/receipts/parse", files={"image": ("r.txt", b"hello", "text/plain")})
    assert resp.status_code == 400


def test_priced_lines_kept_only_when_they_match_the_items():
    lines = [{"kind": "item", "amount": 1, "y": 100}, {"kind": "other", "amount": 1, "y": 200}]
    one_item = {**RAW, "items": RAW["items"][:1]}
    assert receipt.normalize({**one_item, "priced_lines": lines})["lines"] == [
        {"kind": "item", "y": 100}, {"kind": "other", "y": 200}]
    # Two items on the receipt but one item line: unusable, so dropped.
    assert receipt.normalize({**RAW, "items": RAW["items"][:2], "priced_lines": lines})["lines"] == []
    assert receipt.normalize({**one_item, "priced_lines": [{"kind": "item", "amount": 1, "y": "?"}]})["lines"] == []


@pytest.mark.parametrize("raw, iso", [
    ("2026-10-24", "2026-10-24"),
    ("10/24/2026 8:14 PM", "2026-10-24"),
    ("10/22/26 13:02", "2026-10-22"),
    ("Oct 24, 2026", "2026-10-24"),
    ("24 Oct 2026", "2026-10-24"),
    ("Table 7", None),
    (None, None),
])
def test_dates_become_iso(raw, iso):
    assert receipt.iso_date(raw) == iso


def costco_raw(**over):
    raw = {
        "merchant": "COSTCO WHOLESALE", "date": "10/31/2026", "currency": "USD",
        "items": [
            {"name": "SLCD SALAME", "quantity": 1, "amount": 13.99, "discount_for": None},
            {"name": "0000395766 / 820590", "quantity": 1, "amount": -4.00, "discount_for": 1},
            {"name": "DOTS PRETZEL", "quantity": 1, "amount": 9.99, "discount_for": None},
            {"name": "MANDARINS", "quantity": 1, "amount": 4.69, "discount_for": None},
            {"name": "0000397358 /1801", "quantity": 1, "amount": -2.00, "discount_for": 4},
        ],
        "subtotal": 22.67, "tax": 0, "tip": None, "other_charges": [], "total": 22.67,
        "priced_lines": [{"kind": "item", "amount": a, "y": 100 + 20 * k}
                         for k, a in enumerate([13.99, -4, 9.99, 4.69, -2])]
                        + [{"kind": "other", "amount": 22.67, "y": 300}],
    }
    raw.update(over)
    return raw


def test_costco_discounts_fold_into_their_items():
    r = receipt.normalize(costco_raw())
    assert [(i["id"], i["name"], i["amount_cents"], i.get("savings_cents")) for i in r["items"]] == [
        (1, "SLCD SALAME", 999, 400), (2, "DOTS PRETZEL", 999, None), (3, "MANDARINS", 269, 200)]
    assert all(c["ok"] for c in r["checks"])
    # The discount lines are still priced lines on the photo, just not items.
    assert [l["kind"] for l in r["lines"]] == ["item", "other", "item", "item", "other", "other"]


def test_discount_without_a_valid_target_stays_a_line():
    raw = costco_raw()
    raw["items"][1]["discount_for"] = 9       # no such item
    raw["items"][4]["discount_for"] = None    # not said
    r = receipt.normalize(raw)
    assert [i["amount_cents"] for i in r["items"]] == [1399, -400, 999, 469, -200]


def test_discount_bigger_than_its_item_is_not_folded():
    raw = costco_raw()
    raw["items"][1]["amount"] = -20.00
    r = receipt.normalize(raw)
    assert r["items"][0]["amount_cents"] == 1399 and r["items"][1]["amount_cents"] == -2000


@pytest.mark.parametrize("raw, name", [
    ("E  782796 KSWTR40PK", "KSWTR40PK"),
    ("1462714 KS ORG A2 PR", "KS ORG A2 PR"),
    ("2% MILK 1GAL", "2% MILK 1GAL"),
    ("0000395766 / 820590", "0000395766 / 820590"),   # nothing left to name: keep it
    ("Margherita Pizza", "Margherita Pizza"),
])
def test_item_names_drop_product_codes(raw, name):
    assert receipt.item_name(raw) == name


def test_lines_still_usable_when_discounts_were_labelled_other():
    raw = costco_raw()
    for k in (1, 4):
        raw["priced_lines"][k]["kind"] = "other"
    r = receipt.normalize(raw)
    assert sum(l["kind"] == "item" for l in r["lines"]) == len(r["items"]) == 3
