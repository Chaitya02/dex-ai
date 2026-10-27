import json

import pytest
from fastapi.testclient import TestClient

from dex_ai import locate
from dex_ai.app import app
from tests.test_receipt import png_bytes

client = TestClient(app)

W, H = 640, 850
PAPER = {"x1": 0, "y1": 0, "x2": W, "y2": H, "w": W, "h": H}


def box(x1, cy, x2, height=20):
    return {"x1": x1, "y1": cy - height / 2, "x2": x2, "y2": cy + height / 2, "w": W, "h": H, "c": 0.6}


def line(cy, tilt=0, qty=True):
    """A priced line: optional quantity digit on the left, price on the right."""
    out = [box(540, cy, 590)]
    if qty:
        out.append(box(48, cy + tilt, 60))
    return out


def receipt(item_ys, footer_ys):
    return {
        "items": [{"id": i + 1, "name": f"x{i}", "quantity": 1, "amount_cents": 100, "y": y}
                  for i, y in enumerate(item_ys)],
        "footer_ys": footer_ys,
    }


ITEM_CY = [230, 272, 314, 356, 398, 440]
FOOTER_CY = [520, 562, 604, 646]


def numbers(extra=(), tilt=0):
    nums = [b for cy in ITEM_CY for b in line(cy, tilt)]
    nums += [b for cy in FOOTER_CY for b in line(cy, qty=False)]
    for cy in extra:
        nums += line(cy, qty=False)
    return nums


def ys(px_list, drift=1.0, offset=0):
    """Pixel centres -> the reader's 0-1000 positions, optionally drifting."""
    return [round((p * drift + offset) * 1000 / H) for p in px_list]


def placed_centres(out):
    return [round((b["y1"] + b["y2"]) / 2) for _, b in sorted(out["items"].items())]


def test_parse_boxes():
    text = ("<0f>0<|box;x1=181;y1=365;x2=556;y2=486;w=1516;h=1600;c=0.9|><|mask;x=0;y=0;data=!|>,"
            "<0f>1<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|>")
    b = locate.parse_boxes(text)
    assert b[0]["x1"] == 181 and b[0]["c"] == 0.9 and b[1]["c"] == 1


def test_rows_merge_a_tilted_line():
    rs = locate.rows(line(230, tilt=14) + line(272, tilt=14))
    assert len(rs) == 2 and all(len(r["boxes"]) == 2 for r in rs)


def test_place_exact_layout():
    r = receipt(ys(ITEM_CY), ys(FOOTER_CY))
    out = locate.place(r, PAPER, numbers())
    assert placed_centres(out) == ITEM_CY


def test_place_skips_header_and_footer_numbers():
    # "Table 7" above the items and a phone number below the total.
    r = receipt(ys(ITEM_CY), ys(FOOTER_CY))
    out = locate.place(r, PAPER, numbers(extra=(150, 760)))
    assert out["priced_rows"] == 12 and placed_centres(out) == ITEM_CY


def test_place_corrects_reader_drift():
    # The reader's positions run 12% long and start 15px low; the fit cancels it.
    r = receipt(ys(ITEM_CY, drift=1.12, offset=15), ys(FOOTER_CY, drift=1.12, offset=15))
    out = locate.place(r, PAPER, numbers(extra=(150,)))
    assert placed_centres(out) == ITEM_CY


def test_place_survives_tilt():
    r = receipt(ys(ITEM_CY), ys(FOOTER_CY))
    out = locate.place(r, PAPER, numbers(tilt=14))
    assert len(out["items"]) == 6


def test_place_leaves_unplaceable_items_out():
    # Only three priced rows exist for six items: place what matches, no guesses.
    r = receipt(ys(ITEM_CY), [])
    nums = [b for cy in ITEM_CY[:3] for b in line(cy)]
    out = locate.place(r, PAPER, nums)
    assert placed_centres(out) == ITEM_CY[:3]


def test_place_without_positions_places_nothing():
    r = receipt(ys(ITEM_CY), ys(FOOTER_CY))
    r["items"][0]["y"] = None
    assert locate.place(r, PAPER, numbers())["items"] == {}


def test_boxes_do_not_overlap():
    out = locate.place(receipt(ys(ITEM_CY), ys(FOOTER_CY)), PAPER, numbers())
    boxes = [b for _, b in sorted(out["items"].items())]
    assert all(a["y2"] <= b["y1"] for a, b in zip(boxes, boxes[1:]))


def test_locate_endpoint(monkeypatch):
    def fake_segment(url, prompt):
        assert url.startswith("data:image/png;base64,")
        return [PAPER | {"c": 0.9}] if prompt == "paper" else numbers()

    monkeypatch.setattr(locate, "segment", fake_segment)
    r = receipt(ys(ITEM_CY), ys(FOOTER_CY))
    resp = client.post("/api/receipts/locate", files={"image": ("r.png", png_bytes(), "image/png")},
                       data={"receipt": json.dumps(r)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["width"] == W and set(body["items"]) == {"1", "2", "3", "4", "5", "6"}


def test_locate_endpoint_rejects_bad_receipt():
    resp = client.post("/api/receipts/locate", files={"image": ("r.png", png_bytes(), "image/png")},
                       data={"receipt": "not json"})
    assert resp.status_code == 400


def test_locate_endpoint_maps_sam_errors(monkeypatch):
    def broken(url, prompt):
        raise locate.LocateError("SAM 3.1 took too long", status=504)

    monkeypatch.setattr(locate, "segment", broken)
    resp = client.post("/api/receipts/locate", files={"image": ("r.png", png_bytes(), "image/png")},
                       data={"receipt": json.dumps(receipt([], []))})
    assert resp.status_code == 504
