"""Small, server-side Gnani Speech API client for FinSpect voice input/output."""

from __future__ import annotations

import os
import re
from typing import Any

import requests


BASE_URL = "https://api.vachana.ai"
STT_URL = f"{BASE_URL}/stt/v3"
TTS_URL = f"{BASE_URL}/api/v1/tts/inference"
DEFAULT_TIMEOUT = (5, 60)
MAX_AUDIO_BYTES = 20 * 1024 * 1024


class GnaniAPIError(RuntimeError):
    """Sanitized Gnani API error that never includes request headers or secrets."""


def gnani_api_key() -> str | None:
    """Read the optional API key from server-side process environment only."""
    value = os.getenv("GNANI_API_KEY_ID", "").strip()
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
        if not language_code.strip():
            raise ValueError("Choose a language before transcribing.")

        try:
            response = self._session.post(
                STT_URL,
                headers={"X-API-Key-ID": self._api_key},
                data={"language_code": language_code},
                files={"audio_file": (filename, audio, _audio_mime(filename))},
                timeout=self._timeout,
            )
        except requests.RequestException:
            raise GnaniAPIError("Gnani speech-to-text request failed.") from None

        _require_success(response.status_code, "Speech-to-text")
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise GnaniAPIError("Gnani speech-to-text returned an invalid response.") from None
        transcript = payload.get("transcript") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("success") is False
            or not isinstance(transcript, str)
        ):
            raise GnaniAPIError("Gnani speech-to-text could not transcribe this clip.")
        return transcript.strip()

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
            response = self._session.post(
                TTS_URL,
                headers={
                    "X-API-Key-ID": self._api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
        except requests.RequestException:
            raise GnaniAPIError("Gnani text-to-speech request failed.") from None

        _require_success(response.status_code, "Text-to-speech")
        audio = response.content
        if not audio:
            raise GnaniAPIError("Gnani text-to-speech returned empty audio.")
        return audio


def _require_success(status_code: int, operation: str) -> None:
    if not 200 <= status_code < 300:
        # Deliberately omit the response body and request headers from errors.
        raise GnaniAPIError(f"{operation} failed (HTTP {status_code}).")


def _audio_mime(filename: str) -> str:
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
        ".m4a": "audio/mp4",
    }[os.path.splitext(filename.lower())[1]]
