import struct

import httpx
import pytest
from fastapi.testclient import TestClient

from dex_ai import voice
from dex_ai.app import app

client = TestClient(app)


def wav(rate=16000, channels=1, bits=16, frames=1600) -> bytes:
    data = b"\x00\x00" * frames * channels
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * bits // 8,
                      channels * bits // 8, bits)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test")


def test_check_wav_accepts_16k_mono():
    voice.check_wav(wav())
    voice.check_wav(wav(rate=24000))


@pytest.mark.parametrize("bad", [wav(rate=44100), wav(channels=2), b"OggS" + b"\x00" * 60])
def test_check_wav_rejects_other_formats(bad):
    with pytest.raises(voice.VoiceError):
        voice.check_wav(bad)


def test_transcribe_posts_multipart(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(kwargs, url=url)
        return httpx.Response(200, json={"sessionId": "s1", "transcript": " I had the pasta ",
                                         "audioDurationMs": 2100, "turns": []})

    monkeypatch.setattr(httpx, "post", fake_post)
    out = voice.transcribe(wav(), keywords=["Aayush"])
    assert out == {"transcript": "I had the pasta", "duration_ms": 2100, "session_id": "s1"}
    assert seen["url"] == voice.TRANSCRIBE_URL
    assert seen["headers"]["Authorization"] == "Bearer test"
    assert '"keywords": ["Aayush"]' in seen["files"]["request"][1]


def test_transcribe_without_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY")
    with pytest.raises(voice.VoiceError) as e:
        voice.transcribe(wav())
    assert e.value.status == 503


def test_transcribe_endpoint_maps_api_errors(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **k: httpx.Response(401, text="bad key"))
    resp = client.post("/api/voice/transcribe", files={"audio": ("s.wav", wav(), "audio/wav")})
    assert resp.status_code == 502
    assert "401" in resp.json()["detail"]


def test_transcribe_endpoint_passes_keywords(monkeypatch):
    seen = {}

    def fake_transcribe(data, keywords=None):
        seen["keywords"] = keywords
        return {"transcript": "ok", "duration_ms": 1, "session_id": "s"}

    monkeypatch.setattr(voice, "transcribe", fake_transcribe)
    client.post("/api/voice/transcribe", files={"audio": ("s.wav", wav(), "audio/wav")},
                data={"keywords": "Aayush, Ketan,, Garlic Knots"})
    assert seen["keywords"] == ["Aayush", "Ketan", "Garlic Knots"]


def test_index_page_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Split it, out loud" in resp.text
