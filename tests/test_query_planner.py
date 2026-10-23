
import pytest
from pydantic import ValidationError

from finspect.query_planner import (
    CompanyRequest,
    MetricRequest,
    PeriodRequest,
    QueryPlan,
    parse_query_plan,
)


def make_growth_plan() -> QueryPlan:
    return QueryPlan(
        original_question=(
            "How did NVIDIA revenue change in FY2025?"
        ),
        company=CompanyRequest(
            name="NVIDIA",
            ticker="NVDA",
            cik="1045810",
        ),
        period=PeriodRequest(
            period_label="FY2025",
            period_kind="annual",
            fiscal_year=2025,
            comparison_required=True,
            comparison_period="FY2024",
        ),
        benchmark_id="Q01",
        task_type="calculation",
        metrics=[
            MetricRequest(
                name="total_revenue",
                role="primary",
                sources=["xbrl", "financial_table"],
                concept_hint="Revenue from contracts with customers",
            )
        ],
        operation="growth_rate",
        retrieval={
            "sources": ["xbrl", "financial_table"],
            "preferred_sections": [
                "Consolidated Statements of Income"
            ],
            "require_direct_evidence": True,
            "require_period_and_unit_metadata": True,
        },
        answer={
            "include_formula": True,
            "expected_output": "percentage",
        },
    )


def test_valid_growth_plan():
    plan = make_growth_plan()

    assert plan.company.name == "NVIDIA"
    assert plan.benchmark_id == "Q01"
    assert plan.operation == "growth_rate"
    assert plan.period.comparison_required is True
    assert plan.metrics[0].name == "total_revenue"


def test_plan_serializes_to_json():
    plan = make_growth_plan()

    payload = plan.model_dump(mode="json")
    restored = parse_query_plan(payload)

    assert restored == plan


def test_unknown_top_level_fields_are_rejected():
    payload = make_growth_plan().model_dump()
    payload["invented_financial_value"] = 12345

    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)


def test_invalid_benchmark_id_is_rejected():
    payload = make_growth_plan().model_dump()
    payload["benchmark_id"] = "Q99"

    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)


def test_invalid_company_cik_is_rejected():
    with pytest.raises(ValidationError):
        CompanyRequest(
            name="NVIDIA",
            cik="not-a-cik",
        )


def test_quarter_requires_quarterly_period_kind():
    with pytest.raises(ValidationError):
        PeriodRequest(
            period_kind="annual",
            fiscal_quarter=2,
        )


def test_comparison_period_requires_comparison_flag():
    with pytest.raises(ValidationError):
        PeriodRequest(
            period_kind="annual",
            comparison_period="FY2024",
            comparison_required=False,
        )


def test_clarification_requires_a_question():
    payload = make_growth_plan().model_dump()
    payload["needs_clarification"] = True
    payload["clarification_question"] = None

    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)


def test_clarification_task_requires_clarification_flag():
    payload = make_growth_plan().model_dump()
    payload["task_type"] = "clarification"
    payload["needs_clarification"] = False

    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)


def test_unknown_operation_is_rejected():
    payload = make_growth_plan().model_dump()
    payload["operation"] = "execute_arbitrary_python"

    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)


def test_receivables_comparison_plan():
    payload = {
        "original_question": (
            "Compare accounts receivable growth with revenue growth."
        ),
        "company": {"name": "NVIDIA", "ticker": "NVDA"},
        "period": {
            "period_label": "FY2025",
            "period_kind": "annual",
            "fiscal_year": 2025,
            "comparison_required": True,
            "comparison_period": "FY2024",
        },
        "benchmark_id": "Q08",
        "task_type": "comparison",
        "metrics": [
            {
                "name": "accounts_receivable",
                "role": "primary",
                "sources": ["xbrl", "financial_table"],
            },
            {
                "name": "revenue",
                "role": "comparison",
                "sources": ["xbrl", "financial_table"],
            },
        ],
        "operation": "growth_comparison",
        "retrieval": {
            "sources": ["xbrl", "financial_table"],
            "preferred_sections": [],
        },
        "answer": {
            "expected_output": "percentage_points",
        },
    }

    plan = QueryPlan.model_validate(payload)

    assert plan.benchmark_id == "Q08"
    assert len(plan.metrics) == 2
    assert plan.operation == "growth_comparison"


def test_narrative_disclosure_plan():
    payload = {
        "original_question": (
            "What significant regulatory risks does the company disclose?"
        ),
        "company": {"name": "NVIDIA", "ticker": "NVDA"},
        "period": {
            "period_label": "FY2025",
            "period_kind": "annual",
            "fiscal_year": 2025,
        },
        "benchmark_id": "Q16",
        "task_type": "disclosure_analysis",
        "metrics": [
            {
                "name": "regulatory_risk_disclosures",
                "role": "primary",
                "sources": ["narrative", "risk_factors", "notes"],
            }
        ],
        "operation": "regulatory_risk_analysis",
        "retrieval": {
            "sources": ["narrative", "risk_factors", "notes"],
            "preferred_sections": [
                "Risk Factors",
                "Legal Proceedings",
            ],
        },
        "answer": {
            "expected_output": "text",
            "include_citations": True,
        },
    }

    plan = QueryPlan.model_validate(payload)

    assert plan.task_type == "disclosure_analysis"
    assert "risk_factors" in plan.retrieval.sources


def test_material_disclosure_synthesis_requires_multi_part_task():
    payload = make_growth_plan().model_dump()
    payload["operation"] = "material_disclosure_synthesis"
    payload["task_type"] = "disclosure_analysis"

    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)

def test_absolute_change_operation_is_accepted():
    payload = make_growth_plan().model_dump()
    payload["operation"] = "absolute_change"
    payload["answer"]["expected_output"] = "currency"

    plan = QueryPlan.model_validate(payload)

    assert plan.operation == "absolute_change"
    assert plan.answer.expected_output == "currency"


def test_absolute_change_is_not_a_disclosure_analysis_operation():
    payload = make_growth_plan().model_dump()
    payload["operation"] = "absolute_change"
    payload["task_type"] = "disclosure_analysis"

    with pytest.raises(ValidationError):
        QueryPlan.model_validate(payload)