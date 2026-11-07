"""Canonical language registry for FinSpect multilingual input/output.

Provider codes mirror the language codes already configured in the voice UI.
Provider support must still be verified against Gnani's current account/model.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageConfig:
    code: str
    name: str
    translation_code: str
    gnani_stt_code: str | None
    gnani_tts_code: str | None = None
    tts_voice: str | None = None


LANGUAGES: dict[str, LanguageConfig] = {
    "hi": LanguageConfig("hi", "Hindi", "hi", "hi-IN", "hi-IN"),
    "en": LanguageConfig("en", "English", "en", "en-IN", "en-IN", "Kaveri"),
    "ta": LanguageConfig("ta", "Tamil", "ta", "ta-IN", "ta-IN"),
    "te": LanguageConfig("te", "Telugu", "te", "te-IN", "te-IN"),
    "kn": LanguageConfig("kn", "Kannada", "kn", "kn-IN", "kn-IN"),
    "ml": LanguageConfig("ml", "Malayalam", "ml", "ml-IN", "ml-IN"),
    "mr": LanguageConfig("mr", "Marathi", "mr", "mr-IN", "mr-IN"),
    "pa": LanguageConfig("pa", "Punjabi", "pa", "pa-IN", "pa-IN"),
    "bn": LanguageConfig("bn", "Bengali", "bn", "bn-IN", "bn-IN"),
    "gu": LanguageConfig("gu", "Gujarati", "gu", "gu-IN", "gu-IN"),
}


def get_language(code: str) -> LanguageConfig:
    try:
        return LANGUAGES[code.strip().lower()]
    except (KeyError, AttributeError):
        raise ValueError(f"Unsupported FinSpect language: {code!r}") from None


def get_supported_languages() -> tuple[LanguageConfig, ...]:
    return tuple(LANGUAGES.values())


def get_stt_language_code(code: str) -> str:
    config = get_language(code)
    if not config.gnani_stt_code:
        raise ValueError(f"Gnani STT is not configured for {config.name}.")
    return config.gnani_stt_code


def get_tts_configuration(code: str) -> tuple[str, str]:
    config = get_language(code)
    if not config.gnani_tts_code or not config.tts_voice:
        raise ValueError(f"Gnani TTS is not verified/configured for {config.name}.")
    return config.gnani_tts_code, config.tts_voice
