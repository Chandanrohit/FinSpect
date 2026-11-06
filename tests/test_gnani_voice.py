from __future__ import annotations

import io
import wave

import requests
import pytest

from finspect.gnani_voice import (
    GnaniAPIError,
    GnaniVoiceClient,
    STT_URL,
    TTS_URL,
    MAX_AUDIO_DURATION_SECONDS,
    prepare_spoken_summary,
)


def wav_bytes(duration_seconds=0.25):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * int(16000 * duration_seconds))
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, status_code=200, *, payload=None, content=b"audio"):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_stt_uses_server_side_auth_and_returns_transcript():
    session = FakeSession(FakeResponse(payload={"success": True, "transcript": "  revenue growth  "}))
    client = GnaniVoiceClient("secret-value", session=session)

    transcript = client.transcribe(
        wav_bytes(),
        filename="question.wav",
        language_code="en-IN",
    )

    assert transcript == "revenue growth"
    url, request = session.calls[0]
    assert url == STT_URL
    assert request["headers"] == {"X-API-Key-ID": "secret-value"}
    assert request["data"] == {"model": "prisma-v3.0", "language_code": "en-IN"}
    assert request["files"]["audio_file"] == (
        "question.wav",
        wav_bytes(),
        "audio/wav",
    )
    assert request["timeout"] == (5, 60)


def test_tts_requests_wav_and_returns_binary_audio():
    session = FakeSession(FakeResponse(content=b"RIFF audio"))
    client = GnaniVoiceClient("secret-value", session=session)

    audio = client.synthesize("A concise result.")

    assert audio == b"RIFF audio"
    url, request = session.calls[0]
    assert url == TTS_URL
    assert request["headers"]["X-API-Key-ID"] == "secret-value"
    assert request["json"]["model"] == "timbre-v2.5"
    assert request["json"]["voice"] == "Kaveri"
    assert request["json"]["language"] == "en-IN"
    assert request["json"]["audio_config"]["container"] == "wav"


def test_one_shared_key_authenticates_both_voice_services():
    session = FakeSession(FakeResponse(payload={"success": True, "transcript": "question"}))
    client = GnaniVoiceClient("shared-key", session=session)

    client.transcribe(wav_bytes(), filename="question.wav")
    client.synthesize("A concise result.")

    assert session.calls[0][1]["headers"]["X-API-Key-ID"] == "shared-key"
    assert session.calls[1][1]["headers"]["X-API-Key-ID"] == "shared-key"


def test_missing_key_fails_without_making_a_request():
    with pytest.raises(ValueError, match="not configured"):
        GnaniVoiceClient("  ")


@pytest.mark.parametrize(
    "method_kwargs",
    [
        {"audio": b"", "filename": "question.wav"},
        {"audio": wav_bytes(), "filename": "question.exe"},
    ],
)
def test_stt_rejects_invalid_audio_before_network(method_kwargs):
    session = FakeSession(FakeResponse(payload={"success": True, "transcript": "x"}))
    client = GnaniVoiceClient("secret-value", session=session)

    if not method_kwargs["audio"]:
        message = "non-empty"
    elif method_kwargs["filename"].endswith(".exe"):
        message = "accepts WAV"
    else:
        message = ""

    if message:
        with pytest.raises(ValueError, match=message):
            client.transcribe(**method_kwargs)
    else:
        client.transcribe(**method_kwargs)
    assert len(session.calls) == 0


def test_api_failure_does_not_expose_response_body_or_key():
    session = FakeSession(FakeResponse(
        401,
        payload={"detail": {"error_code": "INVALID_API_KEY", "message": "secret-value invalid"}},
    ))
    client = GnaniVoiceClient("secret-value", session=session)

    with pytest.raises(GnaniAPIError) as error:
        client.transcribe(wav_bytes(), filename="question.wav")

    assert "secret-value" not in str(error.value)
    assert error.value.status_code == 401
    assert error.value.category == "INVALID_API_KEY"
    assert "Verify it" in str(error.value)


def test_network_failure_is_sanitized():
    class BrokenSession:
        def post(self, *_args, **_kwargs):
            raise requests.Timeout("secret-value leaked by lower-level error")

    client = GnaniVoiceClient("secret-value", session=BrokenSession())
    with pytest.raises(GnaniAPIError, match="timed out") as error:
        client.transcribe(wav_bytes(), filename="question.wav")
    assert "secret-value" not in str(error.value)
    assert error.value.category == "timeout"


def test_stt_retries_direct_https_if_configured_proxy_is_unavailable(monkeypatch):
    class ProxyFailureSession:
        def post(self, *_args, **_kwargs):
            raise requests.exceptions.ProxyError("proxy at localhost:9 refused connection")

    direct_session = FakeSession(
        FakeResponse(payload={"success": True, "transcript": "direct connection works"})
    )
    direct_session.closed = False
    direct_session.trust_env = True
    direct_session.close = lambda: setattr(direct_session, "closed", True)
    monkeypatch.setattr(requests, "Session", lambda: direct_session)
    client = GnaniVoiceClient("secret-value", session=ProxyFailureSession())

    transcript = client.transcribe(wav_bytes(), filename="question.wav")

    assert transcript == "direct connection works"
    assert direct_session.trust_env is False
    assert direct_session.closed is True


def test_proxy_error_is_sanitized_when_both_routes_fail(monkeypatch):
    class ProxyFailureSession:
        def post(self, *_args, **_kwargs):
            raise requests.exceptions.ProxyError("proxy failure")

    class DirectFailureSession:
        trust_env = True

        def post(self, *_args, **_kwargs):
            raise requests.ConnectionError("direct failure")

        def close(self):
            pass

    monkeypatch.setattr(requests, "Session", DirectFailureSession)
    client = GnaniVoiceClient("secret-value", session=ProxyFailureSession())

    with pytest.raises(GnaniAPIError, match="proxy settings") as error:
        client.transcribe(wav_bytes(), filename="question.wav")

    assert error.value.category == "proxy_error"
    assert "secret-value" not in str(error.value)


def test_stt_rejects_malformed_wav_before_network():
    session = FakeSession(FakeResponse(payload={"success": True, "transcript": "x"}))
    client = GnaniVoiceClient("secret-value", session=session)
    with pytest.raises(ValueError, match="valid, finalized WAV"):
        client.transcribe(b"not wav", filename="question.wav")
    assert session.calls == []


def test_stt_rejects_recordings_over_thirty_seconds_before_network():
    session = FakeSession(FakeResponse(payload={"success": True, "transcript": "x"}))
    client = GnaniVoiceClient("secret-value", session=session)
    audio = wav_bytes(MAX_AUDIO_DURATION_SECONDS + 1)
    with pytest.raises(ValueError, match="up to 30 seconds"):
        client.transcribe(audio, filename="question.wav")
    assert session.calls == []


@pytest.mark.parametrize(
    ("payload", "category"),
    [
        ({"success": True}, "transcription_failed"),
        ({"success": True, "transcript": "   "}, "empty_transcript"),
    ],
)
def test_stt_rejects_missing_or_empty_transcript(payload, category):
    client = GnaniVoiceClient("secret-value", session=FakeSession(FakeResponse(payload=payload)))
    with pytest.raises(GnaniAPIError) as error:
        client.transcribe(wav_bytes(), filename="question.wav")
    assert error.value.category == category


def test_stt_rejects_invalid_json_response():
    client = GnaniVoiceClient("secret-value", session=FakeSession(FakeResponse()))
    with pytest.raises(GnaniAPIError, match="invalid response") as error:
        client.transcribe(wav_bytes(), filename="question.wav")
    assert error.value.category == "invalid_response"


def test_api_failure_keeps_request_id_but_never_echoes_provider_text():
    session = FakeSession(FakeResponse(
        500,
        payload={
            "request_id": "req_123456",
            "error": {"type": "TRANSCRIPTION_FAILED", "message": "private audio content"},
        },
    ))
    client = GnaniVoiceClient("secret-value", session=session)
    with pytest.raises(GnaniAPIError) as error:
        client.transcribe(wav_bytes(), filename="question.wav")
    assert error.value.status_code == 500
    assert error.value.request_id == "req_123456"
    assert "private audio content" not in str(error.value)


def test_spoken_summary_converts_percentage_figures_and_omits_citation_block():
    summary = prepare_spoken_summary(
        "Question: example\n\nResult: conversion was 87.94%; "
        "that is a 6.45 percentage-point decrease.\n\nEvidence: SEC URL",
        "percent",
    )

    assert summary == (
        "conversion was eighty seven point nine four percent; "
        "that is a decrease of six point four five percentage points."
    )
    assert "SEC URL" not in summary


def test_spoken_summary_does_not_send_raw_currency_values_to_tts():
    summary = prepare_spoken_summary(
        "Question: example\n\nResult: NVIDIA result is 123456789.\n\nEvidence:",
        "currency",
    )
    assert "123456789" not in summary
    assert "written answer" in summary
