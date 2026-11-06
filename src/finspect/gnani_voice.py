"""Small, server-side Gnani Speech API client for FinSpect voice input/output."""

from __future__ import annotations

import io
import os
import re
import wave
import streamlit as st
from typing import Any

import requests


BASE_URL = "https://api.vachana.ai"
STT_URL = f"{BASE_URL}/stt/v3"
TTS_URL = f"{BASE_URL}/api/v1/tts/inference"
DEFAULT_TIMEOUT = (5, 60)
MAX_AUDIO_BYTES = 20 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 30
STT_MODEL = "prisma-v3.0"


class GnaniAPIError(RuntimeError):
    """Sanitized Gnani API error that never includes request headers or secrets."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        category: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.request_id = request_id


def gnani_api_key() -> str | None:
    """Read the optional API key from server-side process environment only."""
    value = st.secrets.get("GNANI_API_KEY_ID", "").strip()
    return value or None


def prepare_spoken_summary(answer_text: str, result_unit: str | None = None) -> str:
    """Extract the result line and spell percentage figures for TTS."""
    result_line = next(
        (line.removeprefix("Result: ").strip()
         for line in answer_text.splitlines()
         if line.startswith("Result: ")),
        answer_text.split("\n\n", maxsplit=1)[0].strip(),
    )
    if result_unit == "currency":
        return (
            "FinSpect calculated a currency change. Please check the written "
            "answer for the exact amount and cited filing inputs."
        )

    direction_pattern = re.compile(
        r"(?P<number>-?[\d,]+(?:\.\d+)?)\s+percentage[- ]point\s+"
        r"(?P<direction>increase|decrease)",
        flags=re.IGNORECASE,
    )
    result_line = direction_pattern.sub(
        lambda match: (
            f"{match.group('direction').lower()} of "
            f"{_number_to_spoken_words(match.group('number'))} percentage points"
        ),
        result_line,
    )
    points_pattern = re.compile(
        r"(?P<number>-?[\d,]+(?:\.\d+)?)\s+percentage points?",
        flags=re.IGNORECASE,
    )
    result_line = points_pattern.sub(
        lambda match: (
            f"{_number_to_spoken_words(match.group('number'))} percentage points"
        ),
        result_line,
    )
    percent_pattern = re.compile(r"(?P<number>-?[\d,]+(?:\.\d+)?)%")
    return percent_pattern.sub(
        lambda match: (
            f"{_number_to_spoken_words(match.group('number'))} percent"
        ),
        result_line,
    )


def _number_to_spoken_words(value: str) -> str:
    integer, dot, fraction = value.replace(",", "").partition(".")
    sign = "minus " if integer.startswith("-") else ""
    integer = integer.lstrip("-")
    whole = int(integer)
    words = sign + _integer_to_words(whole)
    if dot:
        digit_words = {
            "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
            "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
        }
        words += " point " + " ".join(digit_words[digit] for digit in fraction)
    return words


def _integer_to_words(value: int) -> str:
    ones = (
        "zero", "one", "two", "three", "four", "five", "six", "seven",
        "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
        "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    )
    tens = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
    scales = ("", "thousand", "million", "billion", "trillion")
    if value == 0:
        return "zero"

    def below_thousand(number: int) -> str:
        parts = []
        if number >= 100:
            parts.extend((ones[number // 100], "hundred"))
            number %= 100
        if number >= 20:
            parts.append(tens[number // 10])
            number %= 10
        if number:
            parts.append(ones[number])
        return " ".join(parts)

    groups = []
    scale_index = 0
    while value:
        group = value % 1000
        if group:
            label = scales[scale_index]
            groups.append(" ".join(part for part in (below_thousand(group), label) if part))
        value //= 1000
        scale_index += 1
    return " ".join(reversed(groups))


class GnaniVoiceClient:
    """Call Gnani REST endpoints without exposing credentials to the browser."""

    def __init__(
        self,
        api_key: str,
        *,
        session: Any | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("Gnani API key is not configured.")
        self._api_key = key
        self._session = session or requests.Session()
        self._timeout = timeout

    def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        language_code: str = "en-IN",
    ) -> str:
        if not audio:
            raise ValueError("Record or select a non-empty audio clip.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("Audio file exceeds FinSpect's 20 MB upload limit.")
        if not filename.lower().endswith((".wav", ".mp3", ".ogg", ".flac", ".aac", ".m4a")):
            raise ValueError("Gnani STT accepts WAV, MP3, OGG, FLAC, AAC, or M4A audio.")
        if filename.lower().endswith(".wav"):
            validate_wav_audio(audio)
        if not language_code.strip():
            raise ValueError("Choose a language before transcribing.")

        try:
            response = self._post_with_proxy_fallback(
                STT_URL,
                headers={"X-API-Key-ID": self._api_key},
                data={"model": STT_MODEL, "language_code": language_code},
                files={"audio_file": (filename, audio, _audio_mime(filename))},
                timeout=self._timeout,
            )
        except requests.Timeout:
            raise GnaniAPIError(
                "Gnani speech-to-text request timed out. Retry with a shorter clip.",
                category="timeout",
            ) from None
        except requests.exceptions.ProxyError:
            raise GnaniAPIError(
                "Gnani could not be reached through the configured proxy or a direct HTTPS connection. Check your network or proxy settings.",
                category="proxy_error",
            ) from None
        except requests.ConnectionError:
            raise GnaniAPIError(
                "Could not connect to Gnani speech-to-text. Check the network and retry.",
                category="connection_error",
            ) from None
        except requests.RequestException:
            raise GnaniAPIError(
                "Gnani speech-to-text request failed before a response was received.",
                category="request_error",
            ) from None

        _require_success(response, "Speech-to-text")
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise GnaniAPIError(
                "Gnani speech-to-text returned an invalid response.",
                category="invalid_response",
            ) from None
        transcript = payload.get("transcript") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("success") is False
            or not isinstance(transcript, str)
        ):
            category, request_id = _response_diagnostics(response)
            message = _SAFE_ERROR_MESSAGES.get(
                category or "",
                "Gnani speech-to-text could not transcribe this clip.",
            )
            raise GnaniAPIError(
                message,
                status_code=int(response.status_code),
                category=category or "transcription_failed",
                request_id=request_id,
            )
        transcript = transcript.strip()
        if not transcript:
            raise GnaniAPIError(
                "Gnani returned an empty transcript. Record a clearer, non-empty clip and retry.",
                category="empty_transcript",
            )
        return transcript

    def synthesize(
        self,
        text: str,
        *,
        voice: str = "Kaveri",
        language: str = "en-IN",
        model: str = "timbre-v2.5",
    ) -> bytes:
        spoken_text = text.strip()
        if not spoken_text:
            raise ValueError("There is no answer text to speak.")
        payload = {
            "text": spoken_text,
            "voice": voice,
            "language": language,
            "model": model,
            "audio_config": {
                "encoding": "linear_pcm",
                "container": "wav",
                "num_channels": 1,
                "sample_rate": 48000,
                "sample_width": 2,
            },
        }
        try:
            response = self._post_with_proxy_fallback(
                TTS_URL,
                headers={
                    "X-API-Key-ID": self._api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
        except requests.Timeout:
            raise GnaniAPIError(
                "Gnani text-to-speech request timed out.", category="timeout"
            ) from None
        except requests.exceptions.ProxyError:
            raise GnaniAPIError(
                "Gnani could not be reached through the configured proxy or a direct HTTPS connection. Check your network or proxy settings.",
                category="proxy_error",
            ) from None
        except requests.ConnectionError:
            raise GnaniAPIError(
                "Could not connect to Gnani text-to-speech. Check the network and retry.",
                category="connection_error",
            ) from None
        except requests.RequestException:
            raise GnaniAPIError(
                "Gnani text-to-speech request failed before a response was received.",
                category="request_error",
            ) from None

        _require_success(response, "Text-to-speech")
        audio = response.content
        if not audio:
            raise GnaniAPIError("Gnani text-to-speech returned empty audio.")
        return audio

    def _post_with_proxy_fallback(self, url: str, **kwargs: Any) -> Any:
        """Retry direct TLS if a configured environment proxy itself is down."""
        try:
            return self._session.post(url, **kwargs)
        except requests.exceptions.ProxyError:
            direct_session = requests.Session()
            direct_session.trust_env = False
            try:
                return direct_session.post(url, **kwargs)
            except requests.Timeout:
                raise
            except requests.RequestException:
                # Keep proxy addresses and underlying exception text out of UI/logs.
                raise requests.exceptions.ProxyError(
                    "Configured proxy and direct HTTPS fallback both failed."
                ) from None
            finally:
                direct_session.close()


def validate_wav_audio(audio: bytes) -> None:
    """Check Streamlit's finalized WAV payload and its supported duration."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            frame_bytes = wav_file.getnchannels() * wav_file.getsampwidth()
            if frame_rate <= 0 or frame_count <= 0:
                raise ValueError("The recording contains no playable audio frames.")
            if len(wav_file.readframes(frame_count)) != frame_count * frame_bytes:
                raise ValueError("The recording is incomplete or truncated.")
            duration = frame_count / frame_rate
    except (wave.Error, EOFError, OSError):
        raise ValueError("The recording is not a valid, finalized WAV audio file.") from None
    if duration > MAX_AUDIO_DURATION_SECONDS:
        raise ValueError("Gnani STT accepts recordings up to 30 seconds long.")


_SAFE_ERROR_MESSAGES = {
    "MISSING_API_KEY": "Gnani credentials are missing. Check the server-side GNANI_API_KEY_ID setting.",
    "INVALID_API_KEY": "Gnani rejected the configured API key. Verify it in the local server configuration.",
    "SCOPE_NOT_ALLOWED": "This Gnani key does not have permission to use speech-to-text.",
    "RATE_LIMITED": "Gnani is processing another request. Wait briefly, then retry.",
    "UNSUPPORTED_AUDIO_FORMAT": "Gnani rejected the audio format. Record a new clip and retry.",
    "AUDIO_CONVERSION_ERROR": "Gnani could not decode the recording. Record a new clip and retry.",
    "MAX_AUDIO_DURATION_EXCEEDED": "The recording is longer than Gnani's 30-second limit.",
    "INVALID_LANGUAGE_CODE": "Gnani does not support the selected language code.",
    "MODEL_UNSUPPORTED_LANGUAGE": "The selected language is not supported by the Gnani transcription model.",
    "UPSTREAM_TIMEOUT": "Gnani speech recognition timed out. Try a shorter clip and retry.",
    "TRANSCRIPTION_FAILED": "Gnani could not recognize the recording. Record a clearer clip and retry.",
}


def _response_diagnostics(response: Any) -> tuple[str | None, str | None]:
    """Extract only allowlisted-shape diagnostic identifiers from Gnani JSON."""
    category = None
    request_id = None
    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error")
            detail = body.get("detail")
            candidate = (
                error.get("type") if isinstance(error, dict) else None
            ) or (body.get("code") if isinstance(body.get("code"), str) else None)
            if not candidate and isinstance(detail, dict):
                candidate = detail.get("error_code")
            if isinstance(candidate, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", candidate):
                category = candidate
            candidate_id = body.get("request_id")
            if isinstance(candidate_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", candidate_id):
                request_id = candidate_id
    except (ValueError, TypeError, AttributeError):
        pass
    return category, request_id


def _require_success(response: Any, operation: str) -> None:
    status_code = int(response.status_code)
    if 200 <= status_code < 300:
        return
    # Never surface the provider's raw body, which may echo submitted content.
    category, request_id = _response_diagnostics(response)

    message = _SAFE_ERROR_MESSAGES.get(category or "")
    if not message:
        message = f"{operation} failed with an API service error. Check the HTTP status and retry."
    raise GnaniAPIError(
        f"{message} (HTTP {status_code}).",
        status_code=status_code,
        category=category,
        request_id=request_id,
    )


def _audio_mime(filename: str) -> str:
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
        ".m4a": "audio/mp4",
    }[os.path.splitext(filename.lower())[1]]
