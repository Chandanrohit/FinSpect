from finspect.language_config import (
    LANGUAGES, get_language, get_supported_languages,
    get_stt_language_code, get_tts_configuration,
)
from finspect.translation import OllamaTranslator


def test_registry_contains_requested_ten_languages():
    assert set(LANGUAGES) == {"hi", "en", "ta", "te", "kn", "ml", "mr", "pa", "bn", "gu"}
    assert len(get_supported_languages()) == 10


def test_language_lookup_is_case_insensitive():
    assert get_language("HI").name == "Hindi"
    assert get_language("en").name == "English"


def test_unknown_language_fails_closed():
    import pytest
    with pytest.raises(ValueError, match="Unsupported"):
        get_language("xx")


def test_language_codes_available_for_voice_ui_languages():
    expected = {
        "hi": "hi-IN", "en": "en-IN", "ta": "ta-IN", "te": "te-IN",
        "kn": "kn-IN", "ml": "ml-IN", "mr": "mr-IN", "pa": "pa-IN",
        "bn": "bn-IN", "gu": "gu-IN",
    }
    assert {key: get_stt_language_code(key) for key in expected} == expected


def test_tts_configuration_does_not_claim_verified_voice_without_voice_id():
    import pytest
    with pytest.raises(ValueError, match="not verified/configured"):
        get_tts_configuration("hi")


def test_english_translation_is_passthrough_without_ollama():
    translator = OllamaTranslator(session=object())
    result = translator.to_english(
        "Calculate NVIDIA revenue growth from FY2024 to FY2025.",
        source_language="en",
    )
    assert result.translated_text == result.original_text
    assert result.status == "passed_through"
    assert result.model


def test_translation_calls_ollama_and_preserves_result_metadata():
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"message": {"content": "Calculate NVIDIA revenue growth from FY2024 to FY2025."}}

    class Session:
        def __init__(self):
            self.calls = []
        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

    session = Session()
    translator = OllamaTranslator(session=session, model="test-model", base_url="http://ollama")
    result = translator.to_english(
        "NVIDIA FY2024 నుండి FY2025 revenue growth calculate చేయండి",
        source_language="te",
    )
    assert result.translated_text.startswith("Calculate NVIDIA")
    assert result.source_language == "te"
    assert result.target_language == "en"
    assert session.calls[0][0] == "http://ollama/api/chat"
    assert session.calls[0][1]["json"]["options"]["temperature"] == 0
