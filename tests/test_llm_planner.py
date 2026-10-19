from unittest.mock import Mock

import pytest
import requests

from finspect.llm_planner import (
    OllamaQueryPlanner,
    QueryPlanningError,
)


def test_empty_question_is_rejected():
    planner = OllamaQueryPlanner()

    with pytest.raises(ValueError, match="must not be empty"):
        planner.plan("   ")


def test_ollama_connection_error_is_wrapped(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("Ollama is offline")

    monkeypatch.setattr("finspect.llm_planner.requests.post", fake_post)

    planner = OllamaQueryPlanner()

    with pytest.raises(QueryPlanningError, match="Could not reach Ollama"):
        planner.plan("Calculate NVIDIA revenue growth.")


def test_invalid_model_output_is_rejected(monkeypatch):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "message": {"content": '{"unexpected_field": true}'}
    }

    monkeypatch.setattr(
        "finspect.llm_planner.requests.post",
        lambda *args, **kwargs: response,
    )

    planner = OllamaQueryPlanner()

    with pytest.raises(QueryPlanningError, match="failed QueryPlan validation"):
        planner.plan("Calculate NVIDIA revenue growth.")


def test_request_uses_configured_model_and_schema(monkeypatch):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "message": {"content": "not valid JSON"}
    }

    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr("finspect.llm_planner.requests.post", fake_post)

    planner = OllamaQueryPlanner(
        model="qwen3.5:4b",
        base_url="http://localhost:11434/",
        timeout=45,
    )

    with pytest.raises(QueryPlanningError):
        planner.plan("Calculate NVIDIA revenue growth.")

    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"]["model"] == "qwen3.5:4b"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["format"] == (
        __import__("finspect.query_planner", fromlist=["QueryPlan"])
        .QueryPlan.model_json_schema()
    )
    assert captured["timeout"] == 45
