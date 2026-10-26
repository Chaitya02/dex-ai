"""Reading a receipt photo into line items, and checking the arithmetic.

Muse Spark reads the image and answers in a fixed JSON schema. The model only
transcribes; every sum is redone here in integer cents, and anything that
doesn't add up is returned as a check the user sees, never silently fixed.
"""
import base64
import json
from decimal import ROUND_HALF_UP, Decimal

from dex_ai import llm

MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Magic bytes -> MIME type. The browser's Content-Type isn't trusted.
_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)

PROMPT = """Read this receipt. Transcribe it exactly; do not compute anything.

- items: every purchased line, in printed order. `name` as printed (expand
  obvious abbreviations only if certain). `quantity` as printed, else 1.
  `amount` is the line's printed total. Discounts and coupons are their own
  items with a negative amount.
- subtotal, tax, tip, total: as printed, or null if not printed.
- other_charges: service charges, delivery or bag fees, as printed.
- If the image is not a receipt, return an empty items list."""

SCHEMA = {
    "type": "object",
    "properties": {
        "merchant": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "currency": {"type": "string", "description": "ISO 4217, e.g. USD"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "amount": {"type": "number"},
                },
                "required": ["name", "quantity", "amount"],
                "additionalProperties": False,
            },
        },
        "subtotal": {"type": ["number", "null"]},
        "tax": {"type": ["number", "null"]},
        "tip": {"type": ["number", "null"]},
        "other_charges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["name", "amount"],
                "additionalProperties": False,
            },
        },
        "total": {"type": ["number", "null"]},
    },
    "required": [
        "merchant", "date", "currency", "items", "subtotal", "tax", "tip",
        "other_charges", "total",
    ],
    "additionalProperties": False,
}


class ReceiptError(Exception):
    """The upload can't be read as a receipt image. The message is user-facing."""


def sniff_image(data: bytes) -> str:
    if len(data) > MAX_IMAGE_BYTES:
        raise ReceiptError("Image is larger than 10 MB")
    for signature, mime in _SIGNATURES:
        if data.startswith(signature):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ReceiptError("Upload a JPEG, PNG or WEBP photo")


def to_cents(amount) -> int | None:
    if amount is None:
        return None
    return int((Decimal(str(amount)) * 100).quantize(Decimal(1), ROUND_HALF_UP))


def normalize(raw: dict) -> dict:
    """Model output -> receipt in integer cents, plus arithmetic checks."""
    items = [
        {
            "id": i,
            "name": item["name"].strip(),
            "quantity": item.get("quantity") or 1,
            "amount_cents": to_cents(item["amount"]),
        }
        for i, item in enumerate(raw.get("items", []), start=1)
    ]
    charges = [
        {"name": c["name"].strip(), "amount_cents": to_cents(c["amount"])}
        for c in raw.get("other_charges", [])
    ]
    receipt = {
        "merchant": raw.get("merchant"),
        "date": raw.get("date"),
        "currency": raw.get("currency") or "USD",
        "items": items,
        "subtotal_cents": to_cents(raw.get("subtotal")),
        "tax_cents": to_cents(raw.get("tax")),
        "tip_cents": to_cents(raw.get("tip")),
        "other_charges": charges,
        "total_cents": to_cents(raw.get("total")),
    }
    receipt["checks"] = checks(receipt)
    return receipt


def checks(r: dict) -> list[dict]:
    """Every sum the receipt prints, recomputed. A failed check is shown, not fixed."""
    if not r["items"]:
        return [{"ok": False, "check": "items", "message": "No line items found"}]
    out = []
    items_sum = sum(i["amount_cents"] for i in r["items"])
    if r["subtotal_cents"] is not None:
        out.append(_compare("subtotal", "Items add up to the subtotal",
                            items_sum, r["subtotal_cents"]))
    base = r["subtotal_cents"] if r["subtotal_cents"] is not None else items_sum
    computed_total = (
        base
        + (r["tax_cents"] or 0)
        + (r["tip_cents"] or 0)
        + sum(c["amount_cents"] for c in r["other_charges"])
    )
    if r["total_cents"] is not None:
        out.append(_compare("total", "Subtotal, tax, tip and charges add up to the total",
                            computed_total, r["total_cents"]))
    return out


def _compare(name: str, label: str, computed: int, printed: int) -> dict:
    diff = printed - computed
    return {
        "ok": diff == 0,
        "check": name,
        "message": label if diff == 0 else f"{label}: off by {diff / 100:+.2f}",
        "computed_cents": computed,
        "printed_cents": printed,
    }


def parse(image: bytes, config: llm.LLMConfig | None = None) -> dict:
    """Receipt photo -> normalized receipt with checks. Raises ReceiptError."""
    mime = sniff_image(image)
    data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    text = llm.chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                ],
            }
        ],
        config,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "receipt", "schema": SCHEMA, "strict": True},
        },
        temperature=0,
    )
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raise ReceiptError("Couldn't read that receipt; try a sharper, flatter photo")
    return normalize(raw)
