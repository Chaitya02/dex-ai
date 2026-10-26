import random
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from dex_ai.app import app
from dex_ai.split import Assignment, SplitError, allocate, split

# The sample receipt (samples/luigis.png), normalized.
LUIGIS = {
    "items": [
        {"id": 1, "name": "Margherita Pizza", "quantity": 1, "amount_cents": 1850},
        {"id": 2, "name": "Penne alla Vodka", "quantity": 1, "amount_cents": 1600},
        {"id": 3, "name": "Chicken Parm", "quantity": 1, "amount_cents": 2100},
        {"id": 4, "name": "Garlic Knots", "quantity": 2, "amount_cents": 900},
        {"id": 5, "name": "Fountain Soda", "quantity": 3, "amount_cents": 825},
        {"id": 6, "name": "Tiramisu", "quantity": 1, "amount_cents": 750},
    ],
    "subtotal_cents": 8025,
    "tax_cents": 532,
    "tip_cents": 1600,
    "other_charges": [],
    "total_cents": 10157,
}

EVERYONE = ["me", "Aayush", "Ketan", "Kunal"]


def equal(*names):
    return {n: Fraction(1) for n in names}


def luigis_assignments():
    return [
        Assignment(1, equal("Aayush", "Ketan")),
        Assignment(2, equal("me")),
        Assignment(3, equal("Kunal")),
        Assignment(4, equal(*EVERYONE)),
        Assignment(5, {"me": Fraction(1), "Aayush": Fraction(1), "Kunal": Fraction(1)}),
        Assignment(6, equal("me", "Kunal")),
    ]


def by_name(result):
    return {p["name"]: p for p in result["people"]}


# ---- allocate ----

def test_allocate_is_exact_and_deterministic():
    assert allocate(100, [1, 1, 1]) == [34, 33, 33]
    assert allocate(1, [1, 1]) == [1, 0]           # tie goes to the first named
    assert allocate(1000, [2, 1]) == [667, 333]
    assert allocate(0, [1, 1]) == [0, 0]


def test_allocate_negative_amounts():
    assert allocate(-100, [1, 1, 1]) == [-34, -33, -33]


def test_allocate_zero_weights_falls_back_to_equal():
    assert allocate(10, [0, 0]) == [5, 5]


@pytest.mark.parametrize("bad", [[], [1, -1]])
def test_allocate_rejects_bad_weights(bad):
    with pytest.raises(SplitError):
        allocate(10, bad)


def test_allocate_never_loses_a_cent():
    rng = random.Random(7)
    for _ in range(2000):
        total = rng.randint(-50_000, 500_000)
        weights = [rng.randint(0, 9) for _ in range(rng.randint(1, 8))]
        parts = allocate(total, weights)
        assert sum(parts) == total
        assert len(parts) == len(weights)


# ---- split ----

def test_luigis_split_matches_hand_calculation():
    r = split(LUIGIS, luigis_assignments(), payer="me")
    p = by_name(r)
    # Items: me 1600 + 225 + 275 + 375 = 2475; Aayush 925 + 225 + 275 = 1425;
    # Ketan 925 + 225 = 1150; Kunal 2100 + 225 + 275 + 375 = 2975. Sum 8025.
    assert {n: p[n]["items_cents"] for n in p} == {
        "Aayush": 1425, "Ketan": 1150, "me": 2475, "Kunal": 2975}
    assert sum(p[n]["total_cents"] for n in p) == 10157
    assert r["complete"] and r["balanced"]
    # Kunal had the most, so pays the most tax and tip.
    assert max(p, key=lambda n: p[n]["total_cents"]) == "Kunal"


def test_settlements_go_to_payer_and_cover_everyone_else():
    r = split(LUIGIS, luigis_assignments(), payer="me")
    p = by_name(r)
    assert {s["from"] for s in r["settlements"]} == {"Aayush", "Ketan", "Kunal"}
    assert all(s["to"] == "me" for s in r["settlements"])
    owed = sum(s["cents"] for s in r["settlements"])
    assert owed + p["me"]["total_cents"] == 10157


def test_people_listed_in_order_first_named():
    r = split(LUIGIS, luigis_assignments(), payer="me")
    assert [x["name"] for x in r["people"]] == ["Aayush", "Ketan", "me", "Kunal"]


def test_weighted_item():
    sodas = [Assignment(5, {"me": Fraction(2), "Kunal": Fraction(1)})]
    p = by_name(split({**LUIGIS, "tax_cents": 0, "tip_cents": 0}, sodas, payer="me"))
    assert p["me"]["items_cents"] == 550 and p["Kunal"]["items_cents"] == 275


def test_equal_tax_tip_mode():
    r = split(LUIGIS, luigis_assignments(), payer="me", tax_tip="equal")
    tips = [next(e["cents"] for e in x["extras"] if e["name"] == "Tip") for x in r["people"]]
    assert tips == [400, 400, 400, 400]


def test_discount_item_and_service_charge():
    receipt = {
        "items": [
            {"id": 1, "name": "Burger", "quantity": 1, "amount_cents": 1500},
            {"id": 2, "name": "Salad", "quantity": 1, "amount_cents": 1000},
            {"id": 3, "name": "Coupon", "quantity": 1, "amount_cents": -500},
        ],
        "tax_cents": 133,
        "tip_cents": None,
        "other_charges": [{"name": "Service fee", "amount_cents": 250}],
        "total_cents": 2383,
    }
    assignments = [
        Assignment(1, equal("me")),
        Assignment(2, equal("Aayush")),
        Assignment(3, equal("me", "Aayush")),
    ]
    r = split(receipt, assignments, payer="me")
    p = by_name(r)
    assert p["me"]["items_cents"] == 1250 and p["Aayush"]["items_cents"] == 750
    assert r["split_total_cents"] == 2383 and r["balanced"]


def test_unassigned_items_are_reported_not_guessed():
    r = split(LUIGIS, luigis_assignments()[:3], payer="me")
    assert not r["complete"] and not r["balanced"]
    assert [u["name"] for u in r["unassigned"]] == ["Garlic Knots", "Fountain Soda", "Tiramisu"]


def test_payer_who_had_nothing_still_listed():
    r = split(LUIGIS, [Assignment(1, equal("Aayush"))], payer="Kunal")
    p = by_name(r)
    assert p["Kunal"]["total_cents"] == 0
    assert r["settlements"][0]["from"] == "Aayush"


def test_mismatched_receipt_is_not_balanced():
    off = {**LUIGIS, "total_cents": 10200}
    assignments = luigis_assignments()
    r = split(off, assignments, payer="me")
    assert r["complete"] and not r["balanced"]


@pytest.mark.parametrize("assignments, message", [
    ([Assignment(99, equal("me"))], "No item with id 99"),
    ([Assignment(1, equal("me")), Assignment(1, equal("Kunal"))], "assigned twice"),
    ([Assignment(1, {})], "Nobody is assigned"),
])
def test_bad_assignments(assignments, message):
    with pytest.raises(SplitError, match=message):
        split(LUIGIS, assignments, payer="me")


def test_random_receipts_always_balance():
    rng = random.Random(11)
    names = ["me", "A", "B", "C", "D", "E"]
    for _ in range(500):
        items = [{"id": i, "name": f"x{i}", "quantity": 1,
                  "amount_cents": rng.randint(-300, 6000)} for i in range(1, rng.randint(2, 12))]
        tax, tip = rng.randint(0, 900), rng.randint(0, 2000)
        receipt = {"items": items, "tax_cents": tax, "tip_cents": tip, "other_charges": [],
                   "total_cents": sum(i["amount_cents"] for i in items) + tax + tip}
        assignments = [
            Assignment(i["id"], {n: Fraction(rng.randint(1, 3))
                                 for n in rng.sample(names, rng.randint(1, len(names)))})
            for i in items
        ]
        r = split(receipt, assignments, payer="me", tax_tip=rng.choice(["proportional", "equal"]))
        assert r["balanced"], r


# ---- /api/split ----

client = TestClient(app)


def test_split_endpoint_people_and_weights():
    resp = client.post("/api/split", json={
        "receipt": LUIGIS,
        "assignments": [
            {"item_id": 1, "people": ["Aayush", "Ketan"]},
            {"item_id": 2, "people": ["me"]},
            {"item_id": 3, "people": ["Kunal"]},
            {"item_id": 4, "people": EVERYONE},
            {"item_id": 5, "weights": {"me": 2, "Kunal": 1}},
            {"item_id": 6, "people": ["me", " Kunal "]},
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["balanced"] and body["split_total_cents"] == 10157
    assert {p["name"] for p in body["people"]} == set(EVERYONE)


def test_split_endpoint_reports_bad_item():
    resp = client.post("/api/split", json={
        "receipt": LUIGIS, "assignments": [{"item_id": 42, "people": ["me"]}]})
    assert resp.status_code == 400
    assert "No item with id 42" in resp.json()["detail"]


def test_split_endpoint_rejects_zero_weight():
    resp = client.post("/api/split", json={
        "receipt": LUIGIS, "assignments": [{"item_id": 1, "weights": {"me": 0}}]})
    assert resp.status_code == 422
