import json

import pytest
from fastapi.testclient import TestClient

from dex_ai import locate
from dex_ai.app import app
import io

from PIL import Image


def png_bytes(size=(640, 850)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()

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


def receipt(item_ys, other_ys, others_first=()):
    """Items at item_ys, then other amount lines at other_ys (others_first go above)."""
    lines = ([{"kind": "other", "y": y} for y in others_first]
             + [{"kind": "item", "y": y} for y in item_ys]
             + [{"kind": "other", "y": y} for y in other_ys])
    return {
        "items": [{"id": i + 1, "name": f"x{i}", "quantity": 1, "amount_cents": 100}
                  for i in range(len(item_ys))],
        "lines": lines,
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


def test_priced_rows_use_the_price_column_only():
    # Quantities 19px lower than their prices would chain lines together if grouped.
    rs = locate.priced_rows(line(230, tilt=19) + line(272, tilt=19), PAPER)
    assert [round(r["cy"]) for r in rs] == [230, 272]


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
    assert placed_centres(out) == ITEM_CY
    # 14px lower at the quantity, ~536px left of the price's right edge.
    assert out["slope"] == pytest.approx(14 / 536, abs=0.002)


def test_tilt_bigger_than_half_a_line_does_not_merge_rows():
    """A curled phone photo: the left end of each line sits ~0.45 of a line lower."""
    r = receipt(ys(ITEM_CY), ys(FOOTER_CY))
    out = locate.place(r, PAPER, numbers(tilt=19))
    assert placed_centres(out) == ITEM_CY
    assert out["slope"] > 0


def test_place_leaves_unplaceable_items_out():
    # Only three priced rows exist for six items: place what matches, no guesses.
    r = receipt(ys(ITEM_CY), [])
    nums = [b for cy in ITEM_CY[:3] for b in line(cy)]
    out = locate.place(r, PAPER, nums)
    assert placed_centres(out) == ITEM_CY[:3]


def test_place_without_lines_places_nothing():
    r = receipt(ys(ITEM_CY), ys(FOOTER_CY))
    r["lines"] = []
    assert locate.place(r, PAPER, numbers())["items"] == {}


def test_unlabeled_amount_after_items_pins_them_despite_a_line_of_drift():
    """The real ALDI case: item positions a whole line low, an unlabeled
    subtotal printed right after the items, footer positions accurate."""
    item_cy = [413, 455, 497, 540]
    extra_cy, footer_cy = 590, [1077, 1123, 1170, 1218, 1320]
    nums = [b for cy in item_cy for b in line(cy, tilt=19)]
    nums += [b for cy in [extra_cy, *footer_cy] for b in line(cy, qty=False)]
    paper = {**PAPER, "h": 1760}
    to_y = lambda px: round(px * 1000 / 1760)
    r = receipt([to_y(c + 45) for c in item_cy], [to_y(extra_cy + 30)] + [to_y(c) for c in footer_cy])
    out = locate.place(r, paper, nums)
    assert placed_centres(out) == item_cy


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


def test_dedupe_keeps_the_most_confident_overlap():
    a = {"x1": 0, "y1": 0, "x2": 10, "y2": 10, "c": 0.9}
    b = {"x1": 1, "y1": 0, "x2": 11, "y2": 10, "c": 0.5}
    c = {"x1": 50, "y1": 0, "x2": 60, "y2": 10, "c": 0.4}
    assert locate.dedupe([b, a, c]) == [a, c]


def test_strips_used_when_full_image_finds_nothing(monkeypatch):
    """Like a real phone photo: the full frame returns no numbers, strips do."""
    calls = []

    def fake_segment(url, prompt):
        calls.append(prompt)
        if prompt == "paper":
            return [PAPER | {"c": 0.9}]
        return [] if len(calls) <= 2 else ["strip"]

    def fake_strips(image, paper):
        assert image.size == (W, H)
        return numbers()

    monkeypatch.setattr(locate, "segment", fake_segment)
    monkeypatch.setattr(locate, "strip_numbers", fake_strips)
    r = receipt(ys(ITEM_CY), ys(FOOTER_CY))
    out = locate.locate(r, png_bytes(), "image/png")
    assert placed_centres(out) == ITEM_CY


def test_strip_numbers_offsets_boxes_into_photo_coordinates(monkeypatch):
    seen = []

    def fake_segment(url, prompt):
        seen.append(url)
        return [{"x1": 5, "y1": 5, "x2": 25, "y2": 20, "w": 0, "h": 0, "c": 0.5 + len(seen) / 100}]

    monkeypatch.setattr(locate, "segment", fake_segment)
    img = Image.new("RGB", (W, H), "white")
    boxes = locate.strip_numbers(img, {"x1": 100, "y1": 0, "x2": 540, "y2": H})
    assert len(seen) > 1
    assert all(b["w"] == W and b["h"] == H and b["x1"] >= 92 for b in boxes)
    assert sorted({b["y1"] for b in boxes}) == sorted(b["y1"] for b in boxes)
