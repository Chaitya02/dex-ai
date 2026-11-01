import json

import pytest
from fastapi.testclient import TestClient

from dex_ai import limits, llm
from dex_ai.app import app
from tests.test_split import LUIGIS

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    limits.reset()
    monkeypatch.delenv("DEX_LIMITS", raising=False)
    monkeypatch.delenv("DEX_TRUST_PROXY", raising=False)
    yield
    limits.reset()


def split_once(headers=None):
    return client.post("/api/split", json={"receipt": LUIGIS, "assignments": []}, headers=headers or {})


def test_off_unless_enabled(monkeypatch):
    monkeypatch.setitem(limits.PER_HOUR, "split", 1)
    assert all(split_once().status_code == 200 for _ in range(3))


def test_per_visitor_hourly_budget(monkeypatch):
    monkeypatch.setenv("DEX_LIMITS", "1")
    monkeypatch.setitem(limits.PER_HOUR, "split", 2)
    assert [split_once().status_code for _ in range(3)] == [200, 200, 429]
    assert "Slow down" in split_once().json()["detail"]


def test_forwarded_for_only_trusted_behind_the_proxy(monkeypatch):
    monkeypatch.setenv("DEX_LIMITS", "1")
    monkeypatch.setitem(limits.PER_HOUR, "split", 1)
    # Not trusted: spoofing the header doesn't buy a fresh budget.
    assert split_once({"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert split_once({"X-Forwarded-For": "2.2.2.2"}).status_code == 429
    limits.reset()
    monkeypatch.setenv("DEX_TRUST_PROXY", "1")
    assert split_once({"X-Forwarded-For": "1.1.1.1, 10.0.0.1"}).status_code == 200
    assert split_once({"X-Forwarded-For": "2.2.2.2, 10.0.0.1"}).status_code == 200
    assert split_once({"X-Forwarded-For": "1.1.1.1, 10.0.0.1"}).status_code == 429


def test_daily_receipt_cap(monkeypatch):
    monkeypatch.setenv("DEX_LIMITS", "1")
    monkeypatch.setattr(limits, "DAILY_RECEIPTS", 1)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: json.dumps({
        "merchant": "x", "date": None, "currency": "USD", "items": [], "subtotal": None, "tax": None,
        "tip": None, "other_charges": [], "total": None, "priced_lines": []}))
    from tests.test_receipt import png_bytes
    first = client.post("/api/receipts/parse", files={"image": ("r.png", png_bytes(), "image/png")})
    second = client.post("/api/receipts/parse", files={"image": ("r.png", png_bytes(), "image/png")})
    assert first.status_code == 200 and second.status_code == 429
    assert "today" in second.json()["detail"]
