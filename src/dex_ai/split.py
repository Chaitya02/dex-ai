"""The split engine: who had what -> what each person owes, to the cent.

No model touches the arithmetic. The agent only decides who had which item;
everything here is integer cents and deterministic:

1. Each item is divided among the people who had it, by weight (equal unless
   told otherwise, e.g. "I had 2 of the 3 sodas" is weights 2 and 1).
2. Tax, tip and each other charge are spread over people in proportion to
   their item subtotal ("proportional"), or equally ("equal").
3. Every division uses the largest-remainder method, so the parts always add
   up to exactly the whole: no lost or invented pennies. Leftover cents go to
   the largest fractional remainders, ties broken by the order people were
   first named, so the same input always gives the same split.

The result says how much each person's share is, line by line, and who pays
whom. The payer's own share is what they spent; everyone else owes the payer.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from fractions import Fraction


class SplitError(Exception):
    """The assignment can't be split as given. The message is user-facing."""


@dataclass
class Assignment:
    item_id: int
    # person -> weight; equal weights mean an equal split
    weights: dict[str, Fraction] = field(default_factory=dict)


def allocate(total: int, weights: list) -> list[int]:
    """Split `total` cents by `weights` so the parts sum exactly to `total`.

    Largest remainder: everyone gets the floor of their exact share, then the
    leftover cents go one each to the largest remainders, earliest first on
    ties. Negative totals (discounts) are allocated as positive and negated.
    """
    if not weights:
        raise SplitError("Nobody to split between")
    weights = [Fraction(w) for w in weights]
    if any(w < 0 for w in weights):
        raise SplitError("Weights can't be negative")
    weight_sum = sum(weights)
    if weight_sum == 0:
        weights, weight_sum = [Fraction(1)] * len(weights), Fraction(len(weights))
    sign, amount = (-1, -total) if total < 0 else (1, total)
    exact = [amount * w / weight_sum for w in weights]
    parts = [int(e) for e in exact]           # floor, since amount >= 0
    leftover = amount - sum(parts)
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - parts[i]), i))
    for i in order[:leftover]:
        parts[i] += 1
    return [sign * p for p in parts]


def split(receipt: dict, assignments: list[Assignment], payer: str,
          tax_tip: str = "proportional") -> dict:
    """Divide a normalized receipt (see receipt.normalize) among people."""
    if tax_tip not in ("proportional", "equal"):
        raise SplitError("tax_tip must be 'proportional' or 'equal'")
    items = {i["id"]: i for i in receipt["items"]}
    unknown = [a.item_id for a in assignments if a.item_id not in items]
    if unknown:
        raise SplitError(f"No item with id {', '.join(map(str, unknown))} on this receipt")
    seen = set()
    for a in assignments:
        if a.item_id in seen:
            raise SplitError(f"Item {a.item_id} is assigned twice")
        seen.add(a.item_id)
        if not a.weights:
            raise SplitError(f"Nobody is assigned to {items[a.item_id]['name']}")

    # People in the order they were first named; the payer is always included.
    people = OrderedDict()
    for a in assignments:
        for name in a.weights:
            people.setdefault(name, None)
    people.setdefault(payer, None)
    names = list(people)
    shares = {n: {"name": n, "items": [], "items_cents": 0, "extras": [], "total_cents": 0}
              for n in names}

    by_id = {a.item_id: a for a in assignments}
    for item in receipt["items"]:            # receipt order, not assignment order
        a = by_id.get(item["id"])
        if a is None:
            continue
        who = list(a.weights)
        parts = allocate(item["amount_cents"], [a.weights[n] for n in who])
        for n, cents in zip(who, parts):
            shares[n]["items"].append({
                "item_id": item["id"],
                "name": item["name"],
                "cents": cents,
                "of_cents": item["amount_cents"],
                "split_ways": len(who),
            })
            shares[n]["items_cents"] += cents

    extras = [("Tax", receipt.get("tax_cents")), ("Tip", receipt.get("tip_cents"))]
    extras += [(c["name"], c["amount_cents"]) for c in receipt.get("other_charges", [])]
    basis = ([max(shares[n]["items_cents"], 0) for n in names] if tax_tip == "proportional"
             else [1] * len(names))
    for label, cents in extras:
        if not cents:
            continue
        for n, part in zip(names, allocate(cents, basis)):
            shares[n]["extras"].append({"name": label, "cents": part})

    for s in shares.values():
        s["total_cents"] = s["items_cents"] + sum(e["cents"] for e in s["extras"])

    unassigned = [{"item_id": i["id"], "name": i["name"], "cents": i["amount_cents"]}
                  for i in receipt["items"] if i["id"] not in by_id]
    split_total = sum(s["total_cents"] for s in shares.values())
    settlements = [
        {"from": n, "to": payer, "cents": shares[n]["total_cents"]}
        for n in names if n != payer and shares[n]["total_cents"] > 0
    ]
    return {
        "payer": payer,
        "tax_tip": tax_tip,
        "people": [shares[n] for n in names],
        "settlements": settlements,
        "unassigned": unassigned,
        "split_total_cents": split_total,
        "receipt_total_cents": receipt.get("total_cents"),
        "complete": not unassigned,
        "balanced": not unassigned and (receipt.get("total_cents") in (None, split_total)),
    }
