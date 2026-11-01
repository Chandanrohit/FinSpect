from decimal import Decimal
from pathlib import Path

import pytest

from finspect.orchestrator import AnnualPeriod, FinSpectOrchestrator
from finspect.plan_normalizer import normalize_query_plan
from finspect.query_planner import (
    CompanyRequest,
    MetricRequest,
    PeriodRequest,
    QueryPlan,
)
from finspect.schema import load_benchmark


QUESTION = "Calculate NVIDIA's revenue growth from FY2024 to FY2025."
CIK = "0001045810"


def make_plan() -> QueryPlan:
    return QueryPlan(
        original_question=QUESTION,
        company=CompanyRequest(name="NVIDIA", ticker="NVDA", cik="1045810"),
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
                sources=["xbrl"],
            )
        ],
        operation="growth_rate",
        retrieval={"sources": ["xbrl"]},
        answer={"include_formula": True, "expected_output": "percentage"},
    )


class FixturePlanner:
    def plan(self, question: str) -> QueryPlan:
        return make_plan()


class FixtureCompanyResolver:
    def resolve(self, *, name=None, ticker=None, cik=None):
        assert name == "NVIDIA Corporation"
        assert ticker == "NVDA"
        assert cik == CIK
        return {"name": "NVIDIA Corporation", "ticker": "NVDA", "cik": CIK}


PERIODS = {
    2024: AnnualPeriod(
        fiscal_year=2024,
        start_date="2023-01-29",
        end_date="2024-01-28",
        form="10-K",
        concept="Revenues",
        filing_date="2024-02-21",
        accession_number="0001045810-24-000029",
    ),
    2025: AnnualPeriod(
        fiscal_year=2025,
        start_date="2024-01-29",
        end_date="2025-01-26",
        form="10-K",
        concept="Revenues",
        filing_date="2025-02-26",
        accession_number="0001045810-25-000023",
    ),
}


FACTS = {
    2024: {
        "cik": CIK,
        "company": "NVIDIA CORP",
        "taxonomy": "us-gaap",
        "concept": "Revenues",
        "label": "Revenue",
        "value": 60_922_000_000,
        "unit": "USD",
        "start_date": "2023-01-29",
        "end_date": "2024-01-28",
        "fiscal_year": 2024,
        "form": "10-K",
        "filing_date": "2024-02-21",
        "accession_number": "0001045810-24-000029",
    },
    2025: {
        "cik": CIK,
        "company": "NVIDIA CORPORATION",
        "taxonomy": "us-gaap",
        "concept": "Revenues",
        "label": "Revenue",
        "value": 130_497_000_000,
        "unit": "USD",
        "start_date": "2024-01-29",
        "end_date": "2025-01-26",
        "fiscal_year": 2025,
        "form": "10-K",
        "filing_date": "2025-02-26",
        "accession_number": "0001045810-25-000023",
    },
}


class FixtureFactRetriever:
    def get_fact(self, *, end_date, **kwargs):
        fact = next(fact for fact in FACTS.values() if fact["end_date"] == end_date)
        assert kwargs["cik"] == CIK
        assert kwargs["unit"] == "USD"
        return fact


def make_orchestrator(fact_retriever=None):
    return FinSpectOrchestrator(
        planner=FixturePlanner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda cik, year: PERIODS[year],
        fact_retriever=fact_retriever or FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
    )


def test_q01_nvidia_fy2024_fy2025_end_to_end_fixture():
    result = make_orchestrator().run(QUESTION)

    assert result.answer.formula_id == "Q01"
    assert result.answer.result_unit == "percent"
    assert Decimal(result.answer.result_value) == (
        (Decimal("130497000000") - Decimal("60922000000"))
        / Decimal("60922000000")
        * Decimal("100")
    )
    assert [item.value for item in result.answer.evidence] == [
        Decimal("60922000000"),
        Decimal("130497000000"),
    ]
    assert [item.accession_number for item in result.answer.evidence] == [
        "0001045810-24-000029",
        "0001045810-25-000023",
    ]
    assert all(item.source_url and "sec.gov/Archives" in item.source_url
               for item in result.answer.evidence)


def test_q01_rejects_fact_for_different_company():
    class WrongCompanyFactRetriever(FixtureFactRetriever):
        def get_fact(self, *, end_date, **kwargs):
            fact = dict(super().get_fact(end_date=end_date, **kwargs))
            fact["company"] = "Microsoft Corporation"
            return fact

    with pytest.raises(ValueError, match="company name does not match"):
        make_orchestrator(WrongCompanyFactRetriever()).run(QUESTION)


@pytest.mark.parametrize(
    ("period", "requested_year", "message"),
    [
        (PERIODS[2024], 2025, "returned FY2024 for requested FY2025"),
        (
            AnnualPeriod(
                fiscal_year=2025,
                start_date="2024-07-01",
                end_date="2025-01-26",
                filing_date="2025-02-26",
                accession_number="0001045810-25-000023",
            ),
            2025,
            "not a full fiscal year",
        ),
        (
            AnnualPeriod(
                fiscal_year=2025,
                start_date="2024-01-29",
                end_date="2025-01-26",
                filing_date=None,
                accession_number=None,
            ),
            2025,
            "filing date and accession number",
        ),
    ],
)
def test_resolved_period_must_be_a_provenanced_full_year(
    period, requested_year, message
):
    with pytest.raises(ValueError, match=message):
        FinSpectOrchestrator._validate_annual_period(period, requested_year)


BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "data" / "benchmark.json"
OPERATION_BY_CALCULATION = {
    "growth_contribution": "growth_contribution",
    "margin_change": "margin_change",
    "expense_growth_contribution": "expense_growth_contribution",
    "change_relationship": "change_relationship",
    "balance_change": "balance_change",
    "liquidity_asset_contribution": "liquidity_asset_contribution",
    "growth_comparison": "growth_comparison",
    "inventory_revenue_growth_comparison": "inventory_revenue_growth_comparison",
    "capital_allocation_ratio": "capital_allocation_ratio",
    "dilution_ratio": "dilution_ratio",
    "equity_component_contribution": "equity_component_contribution",
    "cash_conversion": "cash_conversion",
    "cash_allocation": "cash_allocation",
    "commitment_liquidity_ratio": "commitment_liquidity",
    "sensitivity_ratio": "sensitivity_analysis",
}
DISCLOSURE_OPERATIONS = {
    "Q16": "regulatory_risk_analysis",
    "Q17": "geographic_exposure",
    "Q19": "litigation_analysis",
    "Q20": "material_disclosure_synthesis",
}


def make_unsupported_benchmark_plan(question):
    operation = (
        DISCLOSURE_OPERATIONS.get(question.id)
        or OPERATION_BY_CALCULATION[question.calculation["type"]]
    )
    if question.id == "Q20":
        task_type = "multi_part_analysis"
    elif question.id in DISCLOSURE_OPERATIONS:
        task_type = "disclosure_analysis"
    else:
        task_type = "calculation"

    concepts = question.required_concepts or [question.category]
    sources = ["narrative"] if question.id in DISCLOSURE_OPERATIONS else ["xbrl"]
    return QueryPlan(
        original_question=question.question_template,
        company=CompanyRequest(name="NVIDIA", ticker="NVDA", cik="1045810"),
        period=PeriodRequest(
            period_kind="annual",
            fiscal_year=2025,
            comparison_required=True,
            comparison_period="FY2024",
        ),
        benchmark_id=question.id,
        task_type=task_type,
        metrics=[
            MetricRequest(name=concept, role="primary", sources=sources)
            for concept in concepts
        ],
        operation=operation,
        retrieval={"sources": sources},
    )


@pytest.mark.parametrize(
    "question_id",
    [f"Q{number:02d}" for number in range(2, 21)],
)
def test_other_benchmark_operations_are_explicitly_unsupported(question_id):
    benchmark = load_benchmark(BENCHMARK_PATH)
    question = benchmark.question_map()[question_id]
    plan = make_unsupported_benchmark_plan(question)

    class Planner:
        def plan(self, _question):
            return plan

    orchestrator = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, _year: PERIODS[2025],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
    )
    result = orchestrator.run(question.question_template)

    assert result.answer.result_value is None
    assert result.answer.formula_id is None
    assert result.answer.evidence == ()
    assert "cannot answer this request reliably" in result.answer.text.lower()
