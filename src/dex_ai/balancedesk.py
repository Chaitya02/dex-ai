"""Writing an approved split to Balance Desk, the user's expense app.

Balance Desk exposes a small link API (its routes/link.py):

    GET  /api/link/v1/context   contacts and payment methods
    POST /api/link/v1/splits    one approved split -> one expense, exact shares

configured here with BALANCE_DESK_URL and BALANCE_DESK_TOKEN. Unset, the
splitter still works; it just can't save.

Every save carries an idempotency key chosen when the user approves. Balance
Desk stores the first answer for a key and replays it for any repeat, so this
client can safely retry a save that timed out (the one write in Dex that could
otherwise double-book money), and a double-tapped button saves once.
"""
import os
import string

import httpx

from dex_ai import telemetry

TIMEOUT = 15
RETRIES = 1          # safe only because every write carries an idempotency key


class BalanceDeskError(Exception):
    """Balance Desk refused or couldn't be reached. The message is user-facing."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def configured() -> bool:
    return bool(os.environ.get("BALANCE_DESK_URL") and os.environ.get("BALANCE_DESK_TOKEN"))


def _request(method: str, path: str, json: dict | None = None) -> dict:
    base = os.environ.get("BALANCE_DESK_URL", "").rstrip("/")
    token = os.environ.get("BALANCE_DESK_TOKEN", "")
    if not (base and token):
        raise BalanceDeskError("Balance Desk isn't linked (set BALANCE_DESK_URL and BALANCE_DESK_TOKEN)", 503)
    last: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            resp = httpx.request(method, f"{base}/api/link/v1{path}", json=json, timeout=TIMEOUT,
                                 headers={"Authorization": f"Bearer {token}"})
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last = e
            continue
        except httpx.HTTPError as e:
            raise BalanceDeskError(f"Couldn't reach Balance Desk: {e}")
        telemetry.note(bd_status=resp.status_code, bd_attempts=attempt + 1)
        if resp.status_code == 404:
            raise BalanceDeskError("Balance Desk rejected the link token", 502)
        if resp.status_code == 409 and attempt < RETRIES:
            last = BalanceDeskError("Still saving")
            continue
        try:
            body = resp.json()
        except ValueError:
            raise BalanceDeskError(f"Balance Desk answered {resp.status_code} without JSON")
        if resp.status_code >= 400:
            raise BalanceDeskError(body.get("error") or f"Balance Desk answered {resp.status_code}",
                                   422 if resp.status_code in (400, 422) else 502)
        return body
    if isinstance(last, httpx.TimeoutException):
        raise BalanceDeskError("Balance Desk took too long; your split wasn't lost, try saving again", 504)
    raise BalanceDeskError("Couldn't reach Balance Desk; try saving again")


def context() -> dict:
    """{user, currency, contacts, payment_methods}."""
    return _request("GET", "/context")


def save_split(payload: dict) -> dict:
    """POST one split; returns Balance Desk's answer ({expense, replayed, ...})."""
    return _request("POST", "/splits", json=payload)


def merchant_title(merchant: str | None) -> str:
    """Receipts print merchants in capitals; "LUIGI'S TRATTORIA" -> "Luigi's Trattoria"."""
    if not merchant:
        return "Shared bill"
    return string.capwords(merchant.lower()) if merchant.isupper() else merchant


def payload(receipt: dict, result: dict, *, key: str, payment_method: str | None,
            allow_new_contacts: bool, today: str) -> dict:
    """An approved split (split.split output) as Balance Desk's request body.

    One expense for the whole bill: the total, who paid, and each person's
    exact share. The description says what each person had, so the expense
    explains itself later.
    """
    lines = []
    for p in result["people"]:
        for it in p["items"]:
            lines.append((it["item_id"], it["name"], p["name"]))
    by_item: dict[int, tuple[str, list[str]]] = {}
    for item_id, name, person in lines:
        by_item.setdefault(item_id, (name, []))[1].append("me" if person == "me" else person)
    parts = [f"{name} ({', '.join(who)})" for _, (name, who) in sorted(by_item.items())]
    description = ("Split with Dex: " + "; ".join(parts))[:500]
    body = {
        "idempotency_key": key,
        "title": merchant_title(receipt.get("merchant")),
        "date": receipt.get("date") or today,
        "total": round(result["split_total_cents"] / 100, 2),
        "paid_by": result["payer"],
        "description": description,
        "shares": [{"name": p["name"], "amount": round(p["total_cents"] / 100, 2)}
                   for p in result["people"]],
        "allow_new_contacts": allow_new_contacts,
    }
    if result["payer"] == "me":
        body["payment_method"] = payment_method or ""
    return body
