from decimal import Decimal
import json
from pathlib import Path

import pytest

from finspect.orchestrator import AnnualPeriod, FinSpectOrchestrator
from finspect.edgar.facts import FactRetrievalError
from finspect.plan_normalizer import normalize_query_plan
from finspect.query_planner import (
    CompanyRequest,
    MetricRequest,
    PeriodRequest,
    QueryPlan,
    AnswerRequirements,
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
        assert name in {"NVIDIA", "NVIDIA Corporation"}
        assert ticker == "NVDA"
        assert cik in {CIK, CIK.lstrip("0")}
        return {"name": "NVIDIA Corporation", "ticker": "NVDA", "cik": CIK}


PERIODS = {
    2024: AnnualPeriod(
        fiscal_year=2024,
        start_date="2023-01-30",
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
        "start_date": "2023-01-30",
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

OPERATING_INCOME_FACTS = {
    2024: {**FACTS[2024], "concept": "OperatingIncomeLoss", "label": "Operating income", "value": 32_972_000_000},
    2025: {**FACTS[2025], "concept": "OperatingIncomeLoss", "label": "Operating income", "value": 81_453_000_000},
}

RECEIVABLE_FACTS = {
    2024: {
        **FACTS[2024],
        "concept": "AccountsReceivableNetCurrent",
        "label": "Accounts receivable, net",
        "value": 9_999_000_000,
        "start_date": None,
    },
    2025: {
        **FACTS[2025],
        "concept": "AccountsReceivableNetCurrent",
        "label": "Accounts receivable, net",
        "value": 23_065_000_000,
        "start_date": None,
    },
}

NET_INCOME_FACTS = {
    2024: {**FACTS[2024], "concept": "NetIncomeLoss", "label": "Net income", "value": 29_760_000_000},
    2025: {**FACTS[2025], "concept": "NetIncomeLoss", "label": "Net income", "value": 72_880_000_000},
}

OPERATING_CASH_FLOW_FACTS = {
    2024: {**FACTS[2024], "concept": "NetCashProvidedByUsedInOperatingActivities", "label": "Net cash provided by operating activities", "value": 28_090_000_000},
    2025: {**FACTS[2025], "concept": "NetCashProvidedByUsedInOperatingActivities", "label": "Net cash provided by operating activities", "value": 64_089_000_000},
}


class FixtureFactRetriever:
    def get_fact(self, *, end_date, **kwargs):
        source = (
            OPERATING_INCOME_FACTS
            if kwargs["concept"] == "OperatingIncomeLoss"
            else RECEIVABLE_FACTS
            if kwargs["concept"] == "AccountsReceivableNetCurrent"
            else NET_INCOME_FACTS
            if kwargs["concept"] == "NetIncomeLoss"
            else OPERATING_CASH_FLOW_FACTS
            if kwargs["concept"] == "NetCashProvidedByUsedInOperatingActivities"
            else FACTS
        )
        fact = next(fact for fact in source.values() if fact["end_date"] == end_date)
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


def test_q01_supports_microsoft_and_calendar_year_fiscal_periods():
    question = "Calculate Microsoft's revenue growth from FY2024 to FY2025."
    microsoft_cik = "0000789019"
    plan = make_plan().model_copy(update={
        "original_question": question,
        "company": CompanyRequest(
            name="Microsoft",
            ticker="MSFT",
            cik="789019",
        ),
        "period": PeriodRequest(
            period_label="FY2025",
            period_kind="annual",
            fiscal_year=2025,
            comparison_required=True,
            comparison_period="FY2024",
        ),
    })
    periods = {
        2024: AnnualPeriod(
            fiscal_year=2024,
            start_date="2023-07-01",
            end_date="2024-06-30",
            concept="RevenueFromContractWithCustomerExcludingAssessedTax",
            filing_date="2024-07-30",
            accession_number="0000950170-24-087843",
        ),
        2025: AnnualPeriod(
            fiscal_year=2025,
            start_date="2024-07-01",
            end_date="2025-06-30",
            concept="RevenueFromContractWithCustomerExcludingAssessedTax",
            filing_date="2025-07-30",
            accession_number="0000950170-25-100235",
        ),
    }
    values = {2024: 245_122_000_000, 2025: 281_724_000_000}

    class Planner:
        def plan(self, _question):
            return plan

    class CompanyResolver:
        def resolve(self, **_kwargs):
            return {
                "name": "Microsoft Corporation",
                "ticker": "MSFT",
                "cik": microsoft_cik,
            }

    class FactRetriever:
        def get_fact(self, *, end_date, concept, **_kwargs):
            period = next(p for p in periods.values() if p.end_date == end_date)
            fiscal_year = period.fiscal_year
            return {
                "cik": microsoft_cik,
                "company": "MICROSOFT CORP",
                "taxonomy": "us-gaap",
                "concept": concept,
                "label": "Revenue",
                "value": values[fiscal_year],
                "unit": "USD",
                "start_date": period.start_date,
                "end_date": period.end_date,
                "fiscal_year": fiscal_year,
                "form": "10-K",
                "filing_date": period.filing_date,
                "accession_number": period.accession_number,
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: periods[year],
        fact_retriever=FactRetriever(),
        company_resolver=CompanyResolver(),
    ).run(question)

    expected = (
        Decimal(values[2025] - values[2024]) / Decimal(values[2024]) * 100
    )
    assert result.answer.formula_id == "Q01"
    assert Decimal(result.answer.result_value) == expected
    assert result.plan.company.name == "Microsoft Corporation"
    assert result.plan.company.ticker == "MSFT"
    assert len(result.answer.evidence) == 2


_REVENUE_REFERENCE_MATRIX = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "data"
        / "fixtures"
        / "annual_revenue_reference_matrix.json"
    ).read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize(
    "reference_case",
    _REVENUE_REFERENCE_MATRIX,
    ids=lambda case: (
        f"{case['company']['ticker']}-FY{case['periods'][0]['fiscal_year']}"
        f"-FY{case['periods'][1]['fiscal_year']}"
    ),
)
def test_q01_reference_matrix_runs_through_orchestrator(reference_case):
    company = reference_case["company"]
    period_rows = reference_case["periods"]
    periods = {
        row["fiscal_year"]: AnnualPeriod(
            fiscal_year=row["fiscal_year"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            form=row["form"],
            concept=row["concept"],
            filing_date=row["filing_date"],
            accession_number=row["accession_number"],
            currency=row["unit"],
        )
        for row in period_rows
    }
    prior, current = period_rows
    question = (
        f"Calculate {company['name']}'s revenue growth from "
        f"FY{prior['fiscal_year']} to FY{current['fiscal_year']}."
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "company": CompanyRequest(**company),
        "period": PeriodRequest(
            period_label=f"FY{current['fiscal_year']}",
            period_kind="annual",
            fiscal_year=current["fiscal_year"],
            comparison_required=True,
            comparison_period=f"FY{prior['fiscal_year']}",
        ),
    })

    class Planner:
        def plan(self, _question):
            return plan

    class CompanyResolver:
        def resolve(self, **_kwargs):
            return company

    class FactRetriever:
        def get_fact(self, *, end_date, **_kwargs):
            row = next(item for item in period_rows if item["end_date"] == end_date)
            return {
                "cik": company["cik"],
                "company": company["name"],
                "taxonomy": row["taxonomy"],
                "concept": row["concept"],
                "label": "Revenue",
                "value": row["value"],
                "unit": row["unit"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "fiscal_year": row["fiscal_year"],
                "form": row["form"],
                "filing_date": row["filing_date"],
                "accession_number": row["accession_number"],
                "primary_document": row.get("primary_document"),
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: periods[year],
        fact_retriever=FactRetriever(),
        company_resolver=CompanyResolver(),
    ).run(question)

    assert result.plan.company.cik == company["cik"]
    assert result.plan.company.ticker == company["ticker"]
    assert result.answer.result_value == reference_case["expected_growth_percent"]
    assert [item.accession_number for item in result.answer.evidence] == [
        item["accession_number"] for item in period_rows
    ]
    assert all(
        item.source_url
        and item.source_url.startswith("https://www.sec.gov/Archives/edgar/data/")
        and item.accession_number.replace("-", "") in item.source_url
        for item in result.answer.evidence
    )


_LIQUIDITY_MATRIX = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "data"
        / "fixtures"
        / "liquidity_reference_matrix.json"
    ).read_text(encoding="utf-8")
)["issuers"]
_LIQUIDITY_CASES = [
    (issuer, comparison)
    for issuer in _LIQUIDITY_MATRIX
    for comparison in issuer["comparisons"]
]


_MARGIN_MATRIX = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "data"
        / "fixtures"
        / "annual_margin_reference_matrix.json"
    ).read_text(encoding="utf-8")
)["issuers"]
_MARGIN_CASES = [
    (issuer, comparison)
    for issuer in _MARGIN_MATRIX
    for comparison in issuer["comparisons"]
]


@pytest.mark.parametrize(
    ("issuer", "comparison"),
    _MARGIN_CASES,
    ids=lambda parameter: parameter.get("company", {}).get("ticker")
    if isinstance(parameter, dict) and "company" in parameter
    else f"FY{parameter['prior_year']}-FY{parameter['current_year']}",
)
def test_q03_margin_reference_matrix_runs_through_orchestrator(issuer, comparison):
    company = issuer["company"]
    periods_by_year = {row["fiscal_year"]: row for row in issuer["periods"]}
    prior = periods_by_year[comparison["prior_year"]]
    current = periods_by_year[comparison["current_year"]]
    question = (
        f"How did {company['name']}'s operating margin change from "
        f"FY{prior['fiscal_year']} to FY{current['fiscal_year']}?"
    )
    periods = {
        row["fiscal_year"]: AnnualPeriod(
            fiscal_year=row["fiscal_year"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            form="10-K",
            concept=issuer["revenue_concept"],
            filing_date=row["filing_date"],
            accession_number=row["accession_number"],
            currency="USD",
        )
        for row in issuer["periods"]
    }
    plan = make_plan().model_copy(update={
        "original_question": question,
        "company": CompanyRequest(**company),
        "period": PeriodRequest(
            period_label=f"FY{current['fiscal_year']}",
            period_kind="annual",
            fiscal_year=current["fiscal_year"],
            comparison_required=True,
            comparison_period=f"FY{prior['fiscal_year']}",
        ),
        "operation": "margin_change",
        "metrics": [
            MetricRequest(name="total_revenue", role="primary", sources=["xbrl"]),
            MetricRequest(name="operating_income", role="supporting", sources=["xbrl"]),
        ],
    })

    class Planner:
        def plan(self, _question):
            return plan

    class CompanyResolver:
        def resolve(self, **_kwargs):
            return company

    class FactRetriever:
        def get_fact(self, *, concept, end_date, **_kwargs):
            row = next(item for item in issuer["periods"] if item["end_date"] == end_date)
            is_revenue = concept == issuer["revenue_concept"]
            return {
                "cik": company["cik"], "company": company["name"],
                "taxonomy": "us-gaap", "concept": concept,
                "label": "Revenue" if is_revenue else "Operating income",
                "value": row["revenue"] if is_revenue else row["operating_income"],
                "unit": "USD", "start_date": row["start_date"],
                "end_date": row["end_date"], "fiscal_year": row["fiscal_year"],
                "form": "10-K", "filing_date": row["filing_date"],
                "accession_number": row["accession_number"],
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: periods[year],
        fact_retriever=FactRetriever(),
        company_resolver=CompanyResolver(),
    ).run(question)

    assert result.plan.company.cik == company["cik"]
    assert result.plan.company.ticker == company["ticker"]
    assert Decimal(result.answer.result_value) == Decimal(
        comparison["expected_margin_change_percentage_points"]
    )
    assert result.answer.result_unit == "percentage_points"
    assert len(result.answer.evidence) == 4
    assert {item.accession_number for item in result.answer.evidence} == {
        prior["accession_number"], current["accession_number"]
    }


_CASH_CONVERSION_MATRIX = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "data"
        / "fixtures"
        / "annual_cash_conversion_reference_matrix.json"
    ).read_text(encoding="utf-8")
)["issuers"]
_CASH_CONVERSION_CASES = [
    (issuer, comparison)
    for issuer in _CASH_CONVERSION_MATRIX
    for comparison in issuer["comparisons"]
]


@pytest.mark.parametrize(
    ("issuer", "comparison"),
    _CASH_CONVERSION_CASES,
    ids=lambda parameter: parameter.get("company", {}).get("ticker")
    if isinstance(parameter, dict) and "company" in parameter
    else f"FY{parameter['prior_year']}-FY{parameter['current_year']}",
)
def test_q13_cash_conversion_matrix_runs_through_orchestrator(
    issuer, comparison
):
    company = issuer["company"]
    periods_by_year = {row["fiscal_year"]: row for row in issuer["periods"]}
    prior = periods_by_year[comparison["prior_year"]]
    current = periods_by_year[comparison["current_year"]]
    question = (
        f"What percentage of {company['name']}'s net income was converted into "
        f"operating cash flow in FY{current['fiscal_year']} compared with "
        f"FY{prior['fiscal_year']}?"
    )
    periods = {
        row["fiscal_year"]: AnnualPeriod(
            fiscal_year=row["fiscal_year"], start_date=row["start_date"],
            end_date=row["end_date"], form="10-K", concept="Revenues",
            filing_date=row["filing_date"],
            accession_number=row["accession_number"], currency="USD",
        )
        for row in issuer["periods"]
    }
    plan = make_plan().model_copy(update={
        "original_question": question,
        "company": CompanyRequest(**company),
        "period": PeriodRequest(
            period_label=f"FY{current['fiscal_year']}",
            period_kind="annual", fiscal_year=current["fiscal_year"],
            comparison_required=True,
            comparison_period=f"FY{prior['fiscal_year']}",
        ),
        "operation": "cash_conversion",
        "metrics": [
            MetricRequest(name="net_income", role="primary", sources=["xbrl"]),
            MetricRequest(name="operating_cash_flow", role="supporting", sources=["xbrl"]),
        ],
    })

    class Planner:
        def plan(self, _question):
            return plan

    class CompanyResolver:
        def resolve(self, **_kwargs):
            return company

    class FactRetriever:
        def get_fact(self, *, concept, end_date, **_kwargs):
            row = next(item for item in issuer["periods"] if item["end_date"] == end_date)
            is_net_income = concept == "NetIncomeLoss"
            value = row["net_income"] if is_net_income else row["operating_cash_flow"]
            return {
                "cik": company["cik"], "company": company["name"],
                "taxonomy": "us-gaap", "concept": concept,
                "label": "Net income" if is_net_income else "Operating cash flow",
                "value": value, "unit": "USD", "start_date": row["start_date"],
                "end_date": row["end_date"], "fiscal_year": row["fiscal_year"],
                "form": "10-K", "filing_date": row["filing_date"],
                "accession_number": row["accession_number"],
            }

    result = FinSpectOrchestrator(
        planner=Planner(), normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: periods[year],
        fact_retriever=FactRetriever(), company_resolver=CompanyResolver(),
    ).run(question)

    assert result.plan.company.cik == company["cik"]
    assert result.plan.company.ticker == company["ticker"]
    assert Decimal(result.answer.result_value) == Decimal(
        comparison["expected_current_conversion_percent"]
    )
    assert result.answer.result_unit == "percent"
    assert "percentage-point" in result.answer.text
    assert len(result.answer.evidence) == 4
    assert {item.accession_number for item in result.answer.evidence} == {
        prior["accession_number"], current["accession_number"]
    }


_EARNINGS_MATRIX = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "data"
        / "fixtures"
        / "annual_earnings_relationship_reference_matrix.json"
    ).read_text(encoding="utf-8")
)["issuers"]
_EARNINGS_CASES = [
    (issuer, comparison)
    for issuer in _EARNINGS_MATRIX
    for comparison in issuer["comparisons"]
]


@pytest.mark.parametrize(
    ("issuer", "comparison"),
    _EARNINGS_CASES,
    ids=lambda parameter: parameter.get("company", {}).get("ticker")
    if isinstance(parameter, dict) and "company" in parameter
    else f"FY{parameter['prior_year']}-FY{parameter['current_year']}",
)
def test_q05_earnings_relationship_matrix_runs_through_orchestrator(
    issuer, comparison
):
    company = issuer["company"]
    periods_by_year = {row["fiscal_year"]: row for row in issuer["periods"]}
    prior = periods_by_year[comparison["prior_year"]]
    current = periods_by_year[comparison["current_year"]]
    question = (
        f"How much of the operating-income change from FY{prior['fiscal_year']} "
        f"to FY{current['fiscal_year']} was reflected in net income for "
        f"{company['name']}?"
    )
    periods = {
        row["fiscal_year"]: AnnualPeriod(
            fiscal_year=row["fiscal_year"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            form="10-K",
            concept=issuer["revenue_concept"],
            filing_date=row["filing_date"],
            accession_number=row["accession_number"],
            currency="USD",
        )
        for row in issuer["periods"]
    }
    plan = make_plan().model_copy(update={
        "original_question": question,
        "company": CompanyRequest(**company),
        "period": PeriodRequest(
            period_label=f"FY{current['fiscal_year']}",
            period_kind="annual",
            fiscal_year=current["fiscal_year"],
            comparison_required=True,
            comparison_period=f"FY{prior['fiscal_year']}",
        ),
        "operation": "change_relationship",
        "metrics": [
            MetricRequest(name="net_income", role="primary", sources=["xbrl"]),
            MetricRequest(name="operating_income", role="supporting", sources=["xbrl"]),
        ],
    })

    class Planner:
        def plan(self, _question):
            return plan

    class CompanyResolver:
        def resolve(self, **_kwargs):
            return company

    class FactRetriever:
        def get_fact(self, *, concept, end_date, **_kwargs):
            row = next(item for item in issuer["periods"] if item["end_date"] == end_date)
            is_net_income = concept == "NetIncomeLoss"
            value = row["net_income"] if is_net_income else row["operating_income"]
            return {
                "cik": company["cik"], "company": company["name"],
                "taxonomy": "us-gaap", "concept": concept,
                "label": "Net income" if is_net_income else "Operating income",
                "value": value, "unit": "USD",
                "start_date": row["start_date"], "end_date": row["end_date"],
                "fiscal_year": row["fiscal_year"], "form": "10-K",
                "filing_date": row["filing_date"],
                "accession_number": row["accession_number"],
            }

    result = FinSpectOrchestrator(
        planner=Planner(), normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: periods[year],
        fact_retriever=FactRetriever(), company_resolver=CompanyResolver(),
    ).run(question)

    assert result.plan.company.cik == company["cik"]
    assert result.plan.company.ticker == company["ticker"]
    assert Decimal(result.answer.result_value) == Decimal(
        comparison["expected_relationship_percent"]
    )
    assert result.answer.result_unit == "percent"
    assert len(result.answer.evidence) == 4
    assert {item.accession_number for item in result.answer.evidence} == {
        prior["accession_number"], current["accession_number"]
    }


@pytest.mark.parametrize(
    ("issuer", "comparison"),
    _LIQUIDITY_CASES,
    ids=lambda parameter: parameter.get("company", {}).get("ticker")
    if isinstance(parameter, dict) and "company" in parameter
    else f"FY{parameter['prior_year']}-FY{parameter['current_year']}",
)
def test_q07_liquidity_reference_matrix_runs_through_orchestrator(
    issuer, comparison
):
    company = issuer["company"]
    periods = {row["fiscal_year"]: row for row in issuer["periods"]}
    prior = periods[comparison["prior_year"]]
    current = periods[comparison["current_year"]]
    question = (
        f"How did {company['name']}'s cash, cash equivalents and short-term "
        f"investments or marketable securities change from FY{prior['fiscal_year']} "
        f"to FY{current['fiscal_year']}, and what percentage of the change in "
        "total assets did this represent?"
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "company": CompanyRequest(**company),
        "period": PeriodRequest(
            period_label=f"FY{current['fiscal_year']}",
            period_kind="annual",
            fiscal_year=current["fiscal_year"],
            comparison_required=True,
            comparison_period=f"FY{prior['fiscal_year']}",
        ),
        "operation": "liquidity_asset_contribution",
        "metrics": [
            MetricRequest(
                name="cash_and_cash_equivalents",
                role="primary",
                sources=["xbrl"],
            ),
            MetricRequest(
                name="short_term_investments_or_marketable_securities",
                role="supporting",
                sources=["xbrl"],
            ),
            MetricRequest(
                name="total_assets",
                role="supporting",
                sources=["xbrl"],
            ),
        ],
    })

    class Planner:
        def plan(self, _question):
            return plan

    class CompanyResolver:
        def resolve(self, **_kwargs):
            return company

    class FactRetriever:
        def get_fact(self, *, concept, end_date, **_kwargs):
            period = next(
                row for row in issuer["periods"]
                if row["end_date"] == end_date
            )
            fact = next(
                (period[key] for key in (
                    "cash", "short_term_investments", "total_assets"
                ) if period[key]["concept"] == concept),
                None,
            )
            if fact is None:
                raise FactRetrievalError("Concept not used by this issuer.")
            return {
                "cik": company["cik"],
                "company": company["name"],
                "taxonomy": fact["taxonomy"],
                "concept": fact["concept"],
                "label": fact["concept"],
                "value": fact["value"],
                "unit": fact["unit"],
                "start_date": None,
                "end_date": period["end_date"],
                "fiscal_year": period["fiscal_year"],
                "form": period["form"],
                "filing_date": period["filing_date"],
                "accession_number": period["accession_number"],
                "primary_document": period["primary_document"],
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: AnnualPeriod(
            fiscal_year=periods[year]["fiscal_year"],
            start_date=periods[year]["start_date"],
            end_date=periods[year]["end_date"],
            form=periods[year]["form"],
            filing_date=periods[year]["filing_date"],
            accession_number=periods[year]["accession_number"],
        ),
        fact_retriever=FactRetriever(),
        company_resolver=CompanyResolver(),
    ).run(question)

    assert result.plan.company.ticker == company["ticker"]
    assert result.answer.formula_id == "Q07"
    assert result.answer.result_value == comparison["expected_contribution_percent"]
    assert len(result.answer.evidence) == 6
    assert all(item.source_url and item.source_url.startswith(
        "https://www.sec.gov/Archives/edgar/data/"
    ) for item in result.answer.evidence)


def test_q03_nvidia_operating_margin_change_end_to_end_fixture():
    question = (
        "How did NVIDIA's operating margin change from FY2024 to FY2025?"
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "benchmark_id": "Q03",
        "operation": "margin_change",
        "metrics": [
            MetricRequest(name="revenue", role="supporting", sources=["xbrl"]),
            MetricRequest(name="operating_income", role="primary", sources=["xbrl"]),
        ],
        "answer": AnswerRequirements(
            include_formula=True,
            expected_output="percentage_points",
        ),
    })

    class Planner:
        def plan(self, _question):
            return plan

    orchestrator = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
    )
    result = orchestrator.run(question)

    expected = (
        Decimal("81453000000") / Decimal("130497000000") * Decimal("100")
        - Decimal("32972000000") / Decimal("60922000000") * Decimal("100")
    )
    assert result.answer.formula_id == "Q03"
    assert result.answer.result_unit == "percentage_points"
    assert Decimal(result.answer.result_value) == expected
    assert "8.30 percentage points" in result.answer.text
    assert len(result.answer.evidence) == 4
    assert {item.label for item in result.answer.evidence} == {
        "Revenue",
        "Operating income",
    }
    assert {item.accession_number for item in result.answer.evidence} == {
        "0001045810-24-000029",
        "0001045810-25-000023",
    }


def test_q08_nvidia_receivables_vs_revenue_growth_end_to_end_fixture():
    question = (
        "How did NVIDIA accounts receivable growth compare with revenue "
        "growth from FY2024 to FY2025?"
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "benchmark_id": "Q08",
        "task_type": "comparison",
        "operation": "growth_comparison",
        "metrics": [
            MetricRequest(
                name="accounts_receivable",
                role="primary",
                sources=["xbrl"],
            ),
            MetricRequest(name="revenue", role="comparison", sources=["xbrl"]),
        ],
        "answer": AnswerRequirements(
            include_formula=True,
            expected_output="percentage_points",
        ),
    })

    class Planner:
        def plan(self, _question):
            return plan

    orchestrator = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
    )
    result = orchestrator.run(question)

    ar_growth = (
        (Decimal("23065000000") - Decimal("9999000000"))
        / Decimal("9999000000")
        * Decimal("100")
    )
    revenue_growth = (
        (Decimal("130497000000") - Decimal("60922000000"))
        / Decimal("60922000000")
        * Decimal("100")
    )
    assert result.answer.formula_id == "Q08"
    assert result.answer.result_unit == "percentage_points"
    assert Decimal(result.answer.result_value) == ar_growth - revenue_growth
    assert len(result.answer.evidence) == 4
    assert {item.label for item in result.answer.evidence} == {
        "Revenue",
        "Accounts receivable, net",
    }


def test_q13_nvidia_cash_conversion_comparison_end_to_end_fixture():
    question = (
        "What percentage of NVIDIA net income was converted into operating "
        "cash flow from FY2024 to FY2025, and how did it compare?"
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "benchmark_id": "Q13",
        "task_type": "comparison",
        "operation": "cash_conversion",
        "metrics": [
            MetricRequest(name="net_income", role="primary", sources=["xbrl"]),
            MetricRequest(name="operating_cash_flow", role="comparison", sources=["xbrl"]),
        ],
        "answer": AnswerRequirements(
            include_formula=True,
            expected_output="percentage",
        ),
    })

    class Planner:
        def plan(self, _question):
            return plan

    orchestrator = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
    )
    result = orchestrator.run(question)
    current_ratio = Decimal("64089000000") / Decimal("72880000000") * 100
    prior_ratio = Decimal("28090000000") / Decimal("29760000000") * 100

    assert result.answer.formula_id == "Q13"
    assert result.answer.result_unit == "percent"
    assert Decimal(result.answer.result_value) == current_ratio
    assert f"{current_ratio.quantize(Decimal('0.01'))}%" in result.answer.text
    assert f"{prior_ratio.quantize(Decimal('0.01'))}%" in result.answer.text
    assert (
        f"{abs(current_ratio - prior_ratio).quantize(Decimal('0.01'))} "
        "percentage-point decrease"
    ) in result.answer.text
    assert len(result.answer.evidence) == 4
    assert {item.label for item in result.answer.evidence} == {
        "Net income",
        "Net cash provided by operating activities",
    }


def test_q05_nvidia_earnings_change_relationship_end_to_end_fixture():
    question = (
        "How much of NVIDIA's operating income change from FY2024 to FY2025 "
        "was reflected in net income?"
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "benchmark_id": "Q05",
        "task_type": "comparison",
        "operation": "change_relationship",
        "metrics": [
            MetricRequest(name="operating_income", role="primary", sources=["xbrl"]),
            MetricRequest(name="net_income", role="comparison", sources=["xbrl"]),
        ],
        "answer": AnswerRequirements(
            include_formula=True,
            expected_output="percentage",
        ),
    })

    class Planner:
        def plan(self, _question):
            return plan

    orchestrator = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
    )
    result = orchestrator.run(question)
    expected = (
        (Decimal("72880000000") - Decimal("29760000000"))
        / (Decimal("81453000000") - Decimal("32972000000"))
        * Decimal("100")
    )

    assert result.answer.formula_id == "Q05"
    assert result.answer.result_unit == "percent"
    assert Decimal(result.answer.result_value) == expected
    assert "88.94%" in result.answer.text
    assert len(result.answer.evidence) == 4
    assert {item.label for item in result.answer.evidence} == {
        "Net income",
        "Operating income",
    }


def test_q13_rejects_zero_net_income_denominator():
    class ZeroNetIncomeRetriever(FixtureFactRetriever):
        def get_fact(self, *, end_date, **kwargs):
            fact = dict(super().get_fact(end_date=end_date, **kwargs))
            if kwargs["concept"] == "NetIncomeLoss" and end_date == PERIODS[2025].end_date:
                fact["value"] = 0
            return fact

    question = "Compare NVIDIA cash conversion from FY2024 to FY2025."
    plan = make_plan().model_copy(update={
        "original_question": question,
        "benchmark_id": "Q13",
        "task_type": "comparison",
        "operation": "cash_conversion",
        "metrics": [
            MetricRequest(name="net_income", role="primary", sources=["xbrl"]),
            MetricRequest(name="operating_cash_flow", role="comparison", sources=["xbrl"]),
        ],
    })

    class Planner:
        def plan(self, _question):
            return plan

    orchestrator = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=ZeroNetIncomeRetriever(),
        company_resolver=FixtureCompanyResolver(),
    )
    with pytest.raises(ValueError, match="positive net income in both periods"):
        orchestrator.run(question)


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


def test_revenue_growth_rejects_overlapping_annual_periods():
    overlapping_current = AnnualPeriod(
        fiscal_year=2025,
        start_date="2024-01-01",
        end_date="2025-01-26",
        filing_date="2025-02-26",
        accession_number="0001045810-25-000023",
    )
    orchestrator = FinSpectOrchestrator(
        planner=FixturePlanner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: (
            PERIODS[2024] if year == 2024 else overlapping_current
        ),
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
    )

    with pytest.raises(ValueError, match="periods must not overlap"):
        orchestrator.run(QUESTION)


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
    [
        f"Q{number:02d}"
        for number in range(2, 21)
        if number not in {3, 5, 7, 8, 13}
    ],
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
