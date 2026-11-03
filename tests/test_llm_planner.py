from unittest.mock import Mock

import pytest
import requests

from finspect.llm_planner import (
    OllamaQueryPlanner,
    QueryPlanningError,
    SYSTEM_PROMPT,
    compact_json_schema,
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
        compact_json_schema(
            __import__("finspect.query_planner", fromlist=["QueryPlan"])
            .QueryPlan.model_json_schema()
        )
    )
    assert "description" not in str(captured["payload"]["format"])
    assert captured["timeout"] == 45


def test_system_prompt_routes_q16_to_annual_risk_factor_disclosures():
    assert "Q16 regulatory/trade/export risks: regulatory_risk_analysis" in SYSTEM_PROMPT
    assert "risk_factors" in SYSTEM_PROMPT
    assert "one FY" in SYSTEM_PROMPT


def test_system_prompt_routes_q17_to_geographic_revenue_with_basis_and_caveats():
    assert "Q17 geographic revenue: geographic_exposure" in SYSTEM_PROMPT
    assert "classification basis" in SYSTEM_PROMPT
    assert "do not substitute assets" in SYSTEM_PROMPT


def test_system_prompt_routes_q18_to_period_matched_item_7a_sensitivity():
    assert "Q18 market-risk sensitivity: sensitivity_analysis" in SYSTEM_PROMPT
    assert "scenario, balance, and units" in SYSTEM_PROMPT
    assert "never call a hypothetical loss a forecast" in SYSTEM_PROMPT


def test_system_prompt_routes_q19_to_uncertainty_preserving_legal_disclosures():
    assert "Q19 legal proceedings/contingencies: litigation_analysis" in SYSTEM_PROMPT
    assert "fines, accruals, possible losses, and claims apart" in SYSTEM_PROMPT


def test_system_prompt_routes_q20_to_evidence_limited_cross_section_synthesis():
    assert "Q20 material disclosures: material_disclosure_synthesis" in SYSTEM_PROMPT
    assert "multi_part_analysis" in SYSTEM_PROMPT
    assert "do not assert causation or completeness" in SYSTEM_PROMPT


def test_system_prompt_requires_matching_quarterly_periods_and_forbids_ytd_substitution():
    assert "standalone 10-Q" in SYSTEM_PROMPT
    assert "Never treat YTD as a quarter" in SYSTEM_PROMPT


def test_compact_schema_preserves_constraints_and_drops_descriptions():
    from finspect.query_planner import QueryPlan

    schema = compact_json_schema(QueryPlan.model_json_schema())

    assert "description" not in str(schema)
    assert schema["properties"]["original_question"]["minLength"] == 1
