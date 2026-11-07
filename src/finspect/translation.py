"""Ollama-backed question/answer translation for FinSpect.

Translation preserves financial meaning; it never performs research or arithmetic.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from finspect.language_config import get_language
from finspect.llm_planner import DEFAULT_MODEL, DEFAULT_OLLAMA_URL


class TranslationError(RuntimeError):
    """Translation failed or returned invalid output."""


@dataclass(frozen=True)
class TranslationResult:
    original_text: str
    source_language: str
    translated_text: str | None
    target_language: str
    status: str
    provider: str = "ollama"
    model: str | None = None
    error: str | None = None


class OllamaTranslator:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        session: Any | None = None,
    ) -> None:
        self.model = model or os.getenv("FINSPECT_TRANSLATION_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.getenv("FINSPECT_OLLAMA_URL", DEFAULT_OLLAMA_URL)).rstrip("/")
        self.timeout = timeout or float(os.getenv("FINSPECT_TRANSLATION_TIMEOUT", "120"))
        self.session = session or requests

    def translate(self, text: str, *, source_language: str, target_language: str) -> TranslationResult:
        original = text.strip()
        source = get_language(source_language)
        target = get_language(target_language)
        if not original:
            raise TranslationError("Translation input is empty.")
        if source.code == target.code:
            return TranslationResult(original, source.code, original, target.code, "passed_through", model=self.model)
        prompt = (
            "Translate the user text faithfully. Do not answer it, research it, calculate, "
            "add facts, or resolve ambiguity. Preserve company/ticker names, fiscal years, "
            "dates, metrics, numbers, units, comparison direction, and financial intent. "
            "Return only the translated text, without commentary.\n\n"
            f"Source language: {source.name}\nTarget language: {target.name}\n"
            f"Text:\n{original}"
        )
        try:
            response = self.session.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "think": False,
                    "messages": [
                        {"role": "system", "content": "You are a precise translation engine."},
                        {"role": "user", "content": prompt},
                    ],
                    "options": {"temperature": 0},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            translated = payload["message"]["content"].strip()
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise TranslationError("Ollama translation failed. Check the local model and retry.") from exc
        if not translated or translated.startswith("{"):
            raise TranslationError("Ollama returned empty or malformed translation output.")
        return TranslationResult(original, source.code, translated, target.code, "translated", model=self.model)

    def to_english(self, text: str, *, source_language: str) -> TranslationResult:
        return self.translate(text, source_language=source_language, target_language="en")

    def from_english(self, text: str, *, target_language: str) -> TranslationResult:
        return self.translate(text, source_language="en", target_language=target_language)
