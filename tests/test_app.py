import pytest
from fastapi.testclient import TestClient

from dex_ai.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("DEX_PROVIDER", "DEX_MODEL", "MODEL_API_KEY", "BASETEN_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_health_defaults_to_muse_spark_open():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["llm"] == {"provider": "baseten", "model": "meta-models/muse-spark-open-1026",
                           "key_set": False}


def test_health_reports_bad_provider(monkeypatch):
    monkeypatch.setenv("DEX_PROVIDER", "nope")
    assert "Unknown DEX_PROVIDER" in client.get("/health").json()["llm"]["error"]
