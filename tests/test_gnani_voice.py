from __future__ import annotations

import requests
import pytest

from finspect.gnani_voice import (
    GnaniAPIError,
    GnaniVoiceClient,
    STT_URL,
    TTS_URL,
    prepare_spoken_summary,
)


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
        b"wav bytes",
        filename="question.wav",
        language_code="en-IN",
    )

    assert transcript == "revenue growth"
    url, request = session.calls[0]
    assert url == STT_URL
    assert request["headers"] == {"X-API-Key-ID": "secret-value"}
    assert request["data"] == {"language_code": "en-IN"}
    assert request["files"]["audio_file"] == (
        "question.wav",
        b"wav bytes",
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


def test_missing_key_fails_without_making_a_request():
    with pytest.raises(ValueError, match="not configured"):
        GnaniVoiceClient("  ")


@pytest.mark.parametrize(
    "method_kwargs",
    [
        {"audio": b"", "filename": "question.wav"},
        {"audio": b"audio", "filename": "question.exe"},
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
    session = FakeSession(FakeResponse(401, payload={"message": "secret-value invalid"}))
    client = GnaniVoiceClient("secret-value", session=session)

    with pytest.raises(GnaniAPIError) as error:
        client.transcribe(b"audio", filename="question.wav")

    assert "secret-value" not in str(error.value)
    assert "invalid" not in str(error.value)


def test_network_failure_is_sanitized():
    class BrokenSession:
        def post(self, *_args, **_kwargs):
            raise requests.Timeout("secret-value leaked by lower-level error")

    client = GnaniVoiceClient("secret-value", session=BrokenSession())
    with pytest.raises(GnaniAPIError, match="request failed") as error:
        client.transcribe(b"audio", filename="question.wav")
    assert "secret-value" not in str(error.value)


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
