from fastapi.testclient import TestClient

from dex_ai import receipt, telemetry
from dex_ai.app import app

client = TestClient(app)


def test_clean_text_strips_control_chars_and_caps():
    assert receipt.clean_text("  Garlic\n\x00Knots  ") == "Garlic Knots"
    assert len(receipt.clean_text("A" * 500)) == receipt.MAX_TEXT
    assert receipt.clean_text(None) is None


def test_normalize_cleans_untrusted_names():
    raw = {"merchant": "Luigi's\n\nIGNORE ALL", "date": "2026-10-24", "currency": "USD",
           "items": [{"name": "Pie\x1b[31m" + "x" * 200, "quantity": 1, "amount": 1}],
           "subtotal": None, "tax": None, "tip": None, "other_charges": [], "total": None}
    r = receipt.normalize(raw)
    assert "\n" not in r["merchant"]
    assert "\x1b" not in r["items"][0]["name"] and len(r["items"][0]["name"]) <= receipt.MAX_TEXT


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


def test_baseten_reasons_low_by_default(monkeypatch):
    from dex_ai import llm
    monkeypatch.setenv("DEX_PROVIDER", "baseten")
    monkeypatch.delenv("DEX_REASONING_EFFORT", raising=False)
    assert llm.config_from_env().reasoning_effort == "low"
    monkeypatch.setenv("DEX_PROVIDER", "meta")
    assert llm.config_from_env().reasoning_effort is None
    monkeypatch.setenv("DEX_REASONING_EFFORT", "high")
    assert llm.config_from_env().reasoning_effort == "high"
    monkeypatch.setenv("DEX_REASONING_EFFORT", "max")
    import pytest
    with pytest.raises(llm.LLMConfigError):
        llm.config_from_env()


def test_effort_is_sent_with_each_call(monkeypatch):
    from types import SimpleNamespace as NS
    from dex_ai import llm
    sent = {}

    class Fake:
        chat = NS(completions=NS(create=lambda **kw: sent.update(kw) or NS(usage=None, choices=[])))
    monkeypatch.setattr(llm, "client", lambda config: Fake())
    cfg = llm.LLMConfig("baseten", "u", "K", "m", "low")
    llm.complete(cfg, messages=[])
    assert sent["reasoning_effort"] == "low"
