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
