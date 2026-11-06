from __future__ import annotations

import io
import wave
import asyncio

import httpx
import pytest

from finspect.gnani_voice import GnaniAPIError
from finspect.voice_api import create_app


def request(app, method: str, path: str, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def wav_bytes(duration_seconds: float = 0.25) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * int(16000 * duration_seconds))
    return buffer.getvalue()


class FakeVoiceClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.transcription = None

    def transcribe(self, audio: bytes, *, filename: str, language_code: str) -> str:
        self.transcription = (audio, filename, language_code)
        return "Calculate NVIDIA revenue growth."

    def synthesize(self, text: str) -> bytes:
        self.spoken_text = text
        return b"fake wav bytes"


@pytest.fixture
def voice_client():
    clients = []

    def factory(key):
        client = FakeVoiceClient(key)
        clients.append(client)
        return client

    return clients, factory


def test_health_does_not_expose_configured_key():
    app = create_app(key_provider=lambda: "secret-key")
    response = request(app, "GET", "/health")
    assert response.json() == {"status": "ok", "gnani_configured": True}
    assert "secret-key" not in response.text


def test_backend_rejects_requests_from_non_local_browser_origins(voice_client):
    _clients, factory = voice_client
    app = create_app(key_provider=lambda: "key", client_factory=factory)
    response = request(
        app,
        "POST",
        "/api/voice/transcribe",
        headers={"Origin": "https://attacker.example"},
        data={"language_code": "en-IN"},
        files={"audio_file": ("recording.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 403
    assert "local browser requests only" in response.json()["detail"]


def test_transcription_route_forwards_audio_and_language(voice_client):
    clients, factory = voice_client
    app = create_app(key_provider=lambda: "server-secret", client_factory=factory)
    response = request(
        app,
        "POST",
        "/api/voice/transcribe",
        data={"language_code": "en-IN"},
        files={"audio_file": ("recording.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json() == {"transcript": "Calculate NVIDIA revenue growth."}
    assert clients[0].api_key == "server-secret"
    assert clients[0].transcription == (wav_bytes(), "recording.wav", "en-IN")


def test_transcription_route_rejects_unsupported_filename_before_api(voice_client):
    _clients, factory = voice_client
    app = create_app(key_provider=lambda: "key", client_factory=factory)
    response = request(
        app,
        "POST",
        "/api/voice/transcribe",
        data={"language_code": "en-IN"},
        files={"audio_file": ("recording.webm", b"audio", "audio/webm")},
    )
    assert response.status_code == 415
    assert "must be WAV" in response.json()["detail"]


def test_transcription_route_requires_server_side_key(voice_client):
    _clients, factory = voice_client
    app = create_app(key_provider=lambda: None, client_factory=factory)
    response = request(
        app,
        "POST",
        "/api/voice/transcribe",
        data={"language_code": "en-IN"},
        files={"audio_file": ("recording.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 503
    assert "GNANI_API_KEY_ID" in response.json()["detail"]


def test_transcription_route_returns_sanitized_upstream_diagnostic():
    class BrokenClient:
        def __init__(self, _key):
            pass

        def transcribe(self, *_args, **_kwargs):
            raise GnaniAPIError(
                "Gnani rejected the configured API key. Verify it in the local server configuration. (HTTP 401).",
                status_code=401,
                category="INVALID_API_KEY",
                request_id="req_123",
            )

    app = create_app(key_provider=lambda: "secret", client_factory=BrokenClient)
    response = request(
        app,
        "POST",
        "/api/voice/transcribe",
        data={"language_code": "en-IN"},
        files={"audio_file": ("recording.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == {
        "message": "Gnani rejected the configured API key. Verify it in the local server configuration. (HTTP 401).",
        "upstream_status": 401,
        "category": "INVALID_API_KEY",
        "request_id": "req_123",
    }
    assert "secret" not in response.text


def test_synthesis_route_returns_audio_without_returning_key(voice_client):
    clients, factory = voice_client
    app = create_app(key_provider=lambda: "server-secret", client_factory=factory)
    response = request(app, "POST", "/api/voice/synthesize", json={"text": "A spoken summary."})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"fake wav bytes"
    assert clients[0].api_key == "server-secret"
    assert clients[0].spoken_text == "A spoken summary."


@pytest.mark.parametrize("audio", [b"", b"not a wav"])
def test_transcription_route_rejects_invalid_wav(audio, voice_client):
    _clients, factory = voice_client
    app = create_app(key_provider=lambda: "key", client_factory=factory)
    response = request(
        app,
        "POST",
        "/api/voice/transcribe",
        data={"language_code": "en-IN"},
        files={"audio_file": ("recording.wav", audio, "audio/wav")},
    )
    assert response.status_code == 422
    assert "audio" in response.json()["detail"].lower()

