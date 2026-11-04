from fastapi.testclient import TestClient

from dex_ai import telemetry
from dex_ai.app import app

client = TestClient(app)


def test_percentile_nearest_rank():
    assert telemetry.percentile([], 50) is None
    assert telemetry.percentile([5], 95) == 5
    assert telemetry.percentile(list(range(1, 101)), 95) == 95
    assert telemetry.percentile([10, 20, 30, 40], 50) == 20


def test_turn_records_outcome_and_metrics():
    telemetry.RECENT.clear()
    with telemetry.turn("demo", items=3):
        telemetry.record_llm(120, None, "m")
        telemetry.record_tool("assign_item", True)
        telemetry.record_tool("assign_item", False)
    try:
        with telemetry.turn("demo"):
            raise ValueError("boom")
    except ValueError:
        pass
    first, second = telemetry.RECENT
    assert first["tools"] == ["assign_item", "assign_item!"] and first["llm_calls"] == 1
    assert second["outcome"] == "ValueError"
    m = client.get("/api/metrics").json()["demo"]
    assert m["count"] == 2 and m["errors"] == 1 and m["p50_ms"] is not None


def test_logged_record_has_no_content():
    telemetry.RECENT.clear()
    client.post("/api/assign", json={"receipt": {"items": []}, "transcript": "Aayush had pizza", "people": []})
    for rec in telemetry.RECENT:
        assert "Aayush" not in str(rec) and "pizza" not in str(rec)
