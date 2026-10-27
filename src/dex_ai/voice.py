"""Speech to text with Muse Voice Transcribe.

Only Meta Model API hosts the voice model, so this always uses MODEL_API_KEY,
whatever DEX_PROVIDER says. The browser records and encodes the WAV itself
(mono 16-bit PCM at 16 kHz), so the server never transcodes audio.
"""
import json
import os
import struct
import uuid

import httpx

TRANSCRIBE_URL = "https://api.meta.ai/v1/asr/transcribe"
MODEL = "muse-voice-transcribe-1.0"
MAX_AUDIO_BYTES = 32 * 1024 * 1024   # the API's request cap
TIMEOUT = 30


class VoiceError(Exception):
    """The audio can't be transcribed. The message is user-facing."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def check_wav(data: bytes) -> None:
    """Accept only what the API takes: RIFF/WAVE, PCM, mono, 16-bit, 16/24 kHz."""
    if len(data) > MAX_AUDIO_BYTES:
        raise VoiceError("Recording is too long")
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise VoiceError("Audio must be a WAV file")
    pos = 12
    while pos + 8 <= len(data):
        chunk_id, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if chunk_id == b"fmt ":
            fmt, channels, rate, _, _, bits = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
            if fmt != 1 or channels != 1 or bits != 16 or rate not in (16000, 24000):
                raise VoiceError("Audio must be mono 16-bit PCM at 16 or 24 kHz")
            return
        pos += 8 + size + (size & 1)
    raise VoiceError("WAV file has no format chunk")


def transcribe(wav: bytes, keywords: list[str] | None = None) -> dict:
    """WAV bytes -> {"transcript", "duration_ms", "session_id"}. Raises VoiceError."""
    api_key = os.environ.get("MODEL_API_KEY")
    if not api_key:
        raise VoiceError("MODEL_API_KEY is not set", status=503)
    check_wav(wav)
    settings = {"model": MODEL, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    if keywords:
        settings["keywords"] = keywords
    session_id = f"dex-{uuid.uuid4()}"
    try:
        resp = httpx.post(
            TRANSCRIBE_URL,
            params={"sessionId": session_id},
            headers={"Authorization": f"Bearer {api_key}"},
            files={
                "request": (None, json.dumps(settings), "application/json"),
                "audio": ("speech.wav", wav, "audio/wav"),
            },
            timeout=TIMEOUT,
        )
    except httpx.TimeoutException:
        raise VoiceError("Transcription took too long; try a shorter clip", status=504)
    except httpx.HTTPError as e:
        raise VoiceError(f"Transcription service unreachable: {e}", status=502)
    if resp.status_code != 200:
        raise VoiceError(f"Transcription failed ({resp.status_code}): {resp.text[:300]}",
                         status=502)
    body = resp.json()
    return {
        "transcript": (body.get("transcript") or "").strip(),
        "duration_ms": body.get("audioDurationMs"),
        "session_id": body.get("sessionId", session_id),
    }
