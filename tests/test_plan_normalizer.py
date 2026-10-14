from finspect.query_planner import QueryPlan
from finspect.plan_normalizer import normalize_query_plan


def make_plan(**overrides) -> QueryPlan:
    data = {
        "original_question": (
            "Calculate NVIDIA's revenue growth from FY2024 to FY2025."
        ),
        "company": {
            "name": "NVIDIA Corporation",
            "ticker": "NVDA",
            "cik": "0001067983",  # Deliberately incorrect model output.
        },
        "period": {
            "period_label": None,
            "period_kind": "unspecified",
            "fiscal_year": None,
            "fiscal_quarter": None,
            "comparison_required": False,
            "comparison_period": None,
        },
        "benchmark_id": None,
        "task_type": "calculation",
        "metrics": [
            {
                "name": "Total Revenue",
                "role": "primary",
                "sources": ["financial_table", "financial_table"],
                "required": True,
                "concept_hint": None,
            }
        ],
        "operation": "growth_rate",
        "retrieval": {
            "sources": ["financial_table", "financial_table"],
            "preferred_sections": [],
            "require_direct_evidence": True,
            "require_period_and_unit_metadata": True,
            "max_evidence_items": 8,
        },
        "answer": {
            "include_conclusion": True,
            "include_formula": True,
            "include_input_values": True,
            "include_periods": True,
            "include_units": True,
            "include_citations": True,
            "include_limitations": True,
            "expected_output": "percentage",
        },
        "needs_clarification": False,
        "clarification_question": None,
        "planning_note": "Retrieve revenue for both fiscal years.",
    }
    data.update(overrides)
    return QueryPlan.model_validate(data)


def test_corrects_known_company_cik():
    plan = normalize_query_plan(make_plan())

    assert plan.company.cik == "0001045810"
    assert plan.company.ticker == "NVDA"
    assert plan.company.name == "NVIDIA Corporation"


def test_extracts_explicit_fiscal_years():
    plan = normalize_query_plan(make_plan())

    assert plan.period.fiscal_year == 2025
    assert plan.period.period_label == "FY2025"
    assert plan.period.comparison_required is True
    assert plan.period.comparison_period == "FY2024"


def test_deduplicates_retrieval_sources():
    plan = normalize_query_plan(make_plan())

    assert plan.retrieval.sources == ["financial_table"]
    assert plan.metrics[0].sources == ["financial_table"]


def test_unmapped_benchmark_remains_optional():
    plan = normalize_query_plan(make_plan(benchmark_id=None))

    assert plan.benchmark_id is None


def test_does_not_change_unknown_company_identity():
    plan = make_plan(
        original_question="Analyze Example Robotics' annual report.",
        company={
            "name": "Example Robotics",
            "ticker": "EXRB",
            "cik": None,
        },
        period={
            "period_label": None,
            "period_kind": "unspecified",
            "fiscal_year": None,
            "fiscal_quarter": None,
            "comparison_required": False,
            "comparison_period": None,
        },
        task_type="disclosure_analysis",
        metrics=[
            {
                "name": "Business risks",
                "role": "primary",
                "sources": ["narrative"],
                "required": True,
                "concept_hint": None,
            }
        ],
        operation="regulatory_risk_analysis",
        retrieval={
            "sources": ["narrative", "risk_factors"],
            "preferred_sections": [],
            "require_direct_evidence": True,
            "require_period_and_unit_metadata": False,
            "max_evidence_items": 8,
        },
        answer={
            "include_conclusion": True,
            "include_formula": False,
            "include_input_values": True,
            "include_periods": True,
            "include_units": True,
            "include_citations": True,
            "include_limitations": True,
            "expected_output": "text",
        },
    )

    normalized = normalize_query_plan(plan)

    assert normalized.company.name == "Example Robotics"
    assert normalized.company.ticker == "EXRB"
    assert normalized.company.cik is None
