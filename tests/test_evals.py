"""The eval scorer decides whether a change helped, so it gets tests of its own."""
from fractions import Fraction

from evals import cases as C
from evals.run import _ratio, match_items, score_assign
from evals.synth import generate


def test_synthetic_receipts_are_deterministic_and_add_up():
    a, b = generate(5), generate(5)
    assert a.truth == b.truth
    t = a.truth
    assert t["subtotal_cents"] == sum(i["amount_cents"] for i in t["items"])
    assert t["total_cents"] == t["subtotal_cents"] + t["fee_cents"] + (t["tax_cents"] or 0) + (t["tip_cents"] or 0)
    ys = [i["price_y"] for i in t["items"]]
    assert ys == sorted(ys)


def test_ratio_ignores_scale():
    assert _ratio({"me": 2, "Kunal": 1}) == _ratio({"me": 4.0, "Kunal": 2.0}) == {"me": Fraction(2), "Kunal": Fraction(1)}


def test_match_items_needs_same_cents_and_a_close_name():
    truth = [{"name": "Garlic Knots", "amount_cents": 900}, {"name": "Tiramisu", "amount_cents": 750}]
    read = [{"name": "GARLIC KNOTS", "amount_cents": 900}, {"name": "Cheesecake", "amount_cents": 750}]
    pairs = match_items(read, truth)
    assert pairs[0][1] is read[0] and pairs[1][1] is None


def case(**over):
    base = {"receipt": C.LUIGIS, "expect": {"Tiramisu": {"me": 1}}}
    base.update(over)
    return base


def out(assignments, payer="me", tax_tip="proportional", questions=()):
    return {"assignments": assignments, "payer": payer, "tax_tip": tax_tip,
            "questions": list(questions), "steps": 2, "stopped": None}


def test_exact_match_passes():
    s = score_assign(case(id="x"), out([{"item_id": 6, "weights": {"me": 1.0}}]))
    assert s["pass"] and s["items_wrong"] == 0


def test_an_extra_assignment_fails():
    s = score_assign(case(id="x"), out([{"item_id": 6, "weights": {"me": 1.0}},
                                        {"item_id": 1, "weights": {"Kunal": 1.0}}]))
    assert not s["pass"] and s["wrong"] == ["Margherita Pizza"]


def test_ambiguous_item_must_be_asked_not_guessed():
    c = case(id="x", expect={}, ask=["Fountain Soda"])
    guessed = score_assign(c, out([{"item_id": 5, "weights": {"me": 1.0}}], questions=["?"]))
    silent = score_assign(c, out([]))
    asked = score_assign(c, out([], questions=["Who had the sodas?"]))
    assert not guessed["pass"] and not silent["pass"] and asked["pass"]


def test_payer_and_tax_mode_are_checked():
    c = case(id="x", payer="Kunal", tax_tip="equal")
    assert not score_assign(c, out([{"item_id": 6, "weights": {"me": 1}}]))["pass"]
    assert score_assign(c, out([{"item_id": 6, "weights": {"me": 1}}], payer="Kunal", tax_tip="equal"))["pass"]
