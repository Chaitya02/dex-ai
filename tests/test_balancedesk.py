import httpx
import pytest
from fastapi.testclient import TestClient

from dex_ai import balancedesk
from dex_ai.app import app
from dex_ai.split import split
from tests.test_split import LUIGIS, luigis_assignments

client = TestClient(app)

ASSIGNMENTS = [
    {"item_id": 1, "people": ["Aayush", "Ketan"]},
    {"item_id": 2, "people": ["me"]},
    {"item_id": 3, "people": ["Kunal"]},
    {"item_id": 4, "people": ["me", "Aayush", "Ketan", "Kunal"]},
    {"item_id": 5, "weights": {"me": 1, "Aayush": 1, "Kunal": 1}},
    {"item_id": 6, "people": ["me", "Kunal"]},
]


@pytest.fixture(autouse=True)
def linked(monkeypatch):
    monkeypatch.setenv("BALANCE_DESK_URL", "http://bd.test/")
    monkeypatch.setenv("BALANCE_DESK_TOKEN", "tok")


def respond(*responses):
    """Patch httpx.request to play back responses (or raise exceptions), recording calls."""
    calls = []
    queue = list(responses)

    def fake(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    return calls, fake


def test_payload_is_one_expense_with_exact_shares():
    result = split({**LUIGIS, "merchant": "LUIGI'S TRATTORIA", "date": "2026-10-24"},
                   luigis_assignments(), payer="me")
    body = balancedesk.payload({**LUIGIS, "merchant": "LUIGI'S TRATTORIA", "date": "2026-10-24"},
                               result, key="k-12345678", payment_method="Amex",
                               allow_new_contacts=False, today="2026-10-28")
    assert body["total"] == 101.57 and body["date"] == "2026-10-24"
    assert round(sum(s["amount"] for s in body["shares"]), 2) == 101.57
    assert body["payment_method"] == "Amex" and body["paid_by"] == "me"
    assert body["description"].startswith("Split with Dex: Margherita Pizza (Aayush, Ketan)")


def test_payload_when_a_friend_paid_has_no_payment_method():
    result = split(LUIGIS, luigis_assignments(), payer="Kunal")
    body = balancedesk.payload(LUIGIS, result, key="k-12345678", payment_method="Amex",
                               allow_new_contacts=False, today="2026-10-28")
    assert body["paid_by"] == "Kunal" and "payment_method" not in body
    assert body["title"] == "Shared bill" and body["date"] == "2026-10-28"


def test_timeout_is_retried_with_the_same_key(monkeypatch):
    ok = httpx.Response(201, json={"success": True, "expense": {"id": 7}, "replayed": False})
    calls, fake = respond(httpx.ReadTimeout("slow"), ok)
    monkeypatch.setattr(httpx, "request", fake)
    out = balancedesk.save_split({"idempotency_key": "k-12345678"})
    assert out["expense"]["id"] == 7 and len(calls) == 2
    assert calls[0]["json"] == calls[1]["json"]        # same key both times
    assert calls[0]["url"] == "http://bd.test/api/link/v1/splits"
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"


def test_timeout_twice_is_a_504(monkeypatch):
    _, fake = respond(httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"))
    monkeypatch.setattr(httpx, "request", fake)
    with pytest.raises(balancedesk.BalanceDeskError) as e:
        balancedesk.save_split({})
    assert e.value.status == 504 and "try saving again" in str(e.value)


@pytest.mark.parametrize("status, body, expect", [
    (404, {}, 502),
    (422, {"error": "'Sousheel' isn't one of the user's contacts."}, 422),
    (500, {"error": "boom"}, 502),
])
def test_errors_are_mapped(monkeypatch, status, body, expect):
    _, fake = respond(httpx.Response(status, json=body))
    monkeypatch.setattr(httpx, "request", fake)
    with pytest.raises(balancedesk.BalanceDeskError) as e:
        balancedesk.save_split({})
    assert e.value.status == expect


def test_unlinked(monkeypatch):
    monkeypatch.delenv("BALANCE_DESK_URL")
    assert client.get("/api/balancedesk/context").json() == {"linked": False}
    with pytest.raises(balancedesk.BalanceDeskError):
        balancedesk.context()


def test_context_endpoint(monkeypatch):
    _, fake = respond(httpx.Response(200, json={"user": "C", "currency": "USD",
                                                "contacts": ["Aayush"], "payment_methods": ["Amex"]}))
    monkeypatch.setattr(httpx, "request", fake)
    body = client.get("/api/balancedesk/context").json()
    assert body["linked"] and body["contacts"] == ["Aayush"]


def save_request(**over):
    body = {"receipt": LUIGIS, "assignments": ASSIGNMENTS, "payer": "me",
            "payment_method": "Amex", "idempotency_key": "k-12345678"}
    body.update(over)
    return body


def test_save_recomputes_the_split_server_side(monkeypatch):
    calls, fake = respond(httpx.Response(201, json={"success": True, "expense": {"id": 9}, "replayed": False}))
    monkeypatch.setattr(httpx, "request", fake)
    resp = client.post("/api/balancedesk/save", json=save_request())
    assert resp.status_code == 200 and resp.json()["expense"]["id"] == 9
    sent = calls[0]["json"]
    assert round(sum(s["amount"] for s in sent["shares"]), 2) == 101.57
    assert sent["idempotency_key"] == "k-12345678"


@pytest.mark.parametrize("over, message", [
    ({"assignments": ASSIGNMENTS[:3]}, "Assign every item"),
    ({"payment_method": ""}, "how you paid"),
])
def test_save_refuses_incomplete_splits(over, message):
    resp = client.post("/api/balancedesk/save", json=save_request(**over))
    assert resp.status_code == 400 and message in resp.json()["detail"]


def test_save_needs_a_real_idempotency_key():
    assert client.post("/api/balancedesk/save", json=save_request(idempotency_key="x")).status_code == 422


@pytest.mark.parametrize("raw, title", [
    ("LUIGI'S TRATTORIA", "Luigi's Trattoria"), ("ALDI", "Aldi"),
    ("Trader Joe's", "Trader Joe's"), (None, "Shared bill"),
])
def test_merchant_title(raw, title):
    assert balancedesk.merchant_title(raw) == title
