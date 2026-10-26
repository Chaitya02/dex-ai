import pytest
from fastapi.testclient import TestClient

from dex_ai import llm
from dex_ai.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("DEX_PROVIDER", "DEX_MODEL", "MODEL_API_KEY", "BASETEN_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_health_defaults_to_meta():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["llm"] == {"provider": "meta", "model": "muse-spark-1.3", "key_set": False}


def test_health_reports_bad_provider(monkeypatch):
    monkeypatch.setenv("DEX_PROVIDER", "nope")
    assert "Unknown DEX_PROVIDER" in client.get("/health").json()["llm"]["error"]


def test_chat_without_key_is_503():
    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 503
    assert "MODEL_API_KEY" in resp.json()["detail"]


def test_chat_returns_model_reply(monkeypatch):
    monkeypatch.setenv("DEX_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "test")
    seen = {}

    def fake_chat(messages, config):
        seen["messages"] = messages
        return "Logged $12 for groceries."

    monkeypatch.setattr(llm, "chat", fake_chat)
    resp = client.post("/chat", json={"message": "spent 12 on groceries"})
    assert resp.status_code == 200
    assert resp.json() == {
        "reply": "Logged $12 for groceries.",
        "provider": "baseten",
        "model": "meta-models/muse-spark-open-1026",
    }
    assert seen["messages"][-1] == {"role": "user", "content": "spent 12 on groceries"}
