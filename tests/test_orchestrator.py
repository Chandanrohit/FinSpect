from decimal import Decimal
import json
from pathlib import Path

import pytest

from finspect.orchestrator import AnnualPeriod, FinSpectOrchestrator
from finspect.edgar.facts import FactRetrievalError
from finspect.edgar.parser import FilingParser
from finspect.plan_normalizer import normalize_query_plan
from finspect.narrative_retriever import NarrativeRetriever
from finspect.query_planner import (
    CompanyRequest,
    MetricRequest,
    PeriodRequest,
    QueryPlan,
    AnswerRequirements,
    RetrievalRequirements,
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


def test_q11_nvidia_weighted_average_share_dilution_end_to_end_fixture():
    question = "What percentage of basic weighted-average shares was represented by the dilutive effect of outstanding equity awards in FY2025?"
    plan = make_plan().model_copy(update={
        "original_question": question,
        "period": PeriodRequest(
            period_label="FY2025",
            period_kind="annual",
            fiscal_year=2025,
        ),
        "benchmark_id": "Q11",
        "metrics": [
            MetricRequest(name="basic_weighted_average_shares", role="primary", sources=["xbrl"]),
            MetricRequest(name="dilutive_effect", role="supporting", sources=["xbrl"]),
        ],
        "operation": "dilution_ratio",
        "answer": AnswerRequirements(expected_output="percentage"),
    })

    class Planner:
        def plan(self, _question):
            return plan

    class ShareFactRetriever:
        values = {
            "WeightedAverageNumberOfSharesOutstandingBasic": ("Basic weighted average shares", "24555000000"),
            "WeightedAverageNumberOfDilutedSharesOutstanding": ("Diluted weighted average shares", "24804000000"),
        }

        def get_fact(self, *, concept, **kwargs):
            label, value = self.values[concept]
            assert kwargs["unit"] == "shares"
            return {
                **FACTS[2025],
                "concept": concept,
                "label": label,
                "value": value,
                "unit": "shares",
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=ShareFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
    ).run(question)

    expected = Decimal("249000000") / Decimal("24555000000") * 100
    assert result.answer.formula_id == "Q11"
    assert result.answer.result_unit == "percent"
    assert Decimal(result.answer.result_value) == expected
    assert [item.value for item in result.answer.evidence] == [
        Decimal("24555000000"),
        Decimal("24804000000"),
    ]
    assert all(item.source_url and "sec.gov/Archives" in item.source_url
               for item in result.answer.evidence)


_REPURCHASE_CASES = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "data"
        / "fixtures"
        / "annual_share_repurchase_reference_matrix.json"
    ).read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize(
    "reference_case",
    _REPURCHASE_CASES,
    ids=lambda case: (
        f"{case['company']['ticker']}-FY{case['periods'][0]['fiscal_year']}"
        f"-FY{case['periods'][1]['fiscal_year']}"
    ),
)
def test_q10_share_repurchase_reference_matrix_runs_through_orchestrator(reference_case):
    company = reference_case["company"]
    prior, current = reference_case["periods"]
    periods = {row["fiscal_year"]: row for row in (prior, current)}
    question = (
        f"What amount did {company['name']} spend on share repurchases in "
        f"FY{current['fiscal_year']}, what percentage of operating cash flow "
        f"did that represent, and how did it compare with FY{prior['fiscal_year']}?"
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
        "benchmark_id": "Q10",
        "operation": "capital_allocation_ratio",
        "metrics": [
            MetricRequest(name="share_repurchase_cash", role="primary", sources=["xbrl"]),
            MetricRequest(name="operating_cash_flow", role="denominator", sources=["xbrl"]),
        ],
    })

    class Planner:
        def plan(self, _question):
            return plan

    class CompanyResolver:
        def resolve(self, **_kwargs):
            return company

    class PeriodResolver:
        def __call__(self, _cik, year):
            row = periods[year]
            return AnnualPeriod(
                fiscal_year=year,
                start_date=row["start_date"],
                end_date=row["end_date"],
                form="10-K",
                concept="RevenueFromContractWithCustomerExcludingAssessedTax",
                filing_date=row["filing_date"],
                accession_number=row["accession_number"],
            )

    class FactRetriever:
        def get_fact(self, *, concept, end_date, **kwargs):
            row = next(item for item in (prior, current) if item["end_date"] == end_date)
            is_repurchase = concept == "PaymentsForRepurchaseOfCommonStock"
            assert concept in {
                "PaymentsForRepurchaseOfCommonStock",
                "NetCashProvidedByUsedInOperatingActivities",
            }
            assert kwargs["unit"] == "USD"
            amount = row["share_repurchase_cash"] if is_repurchase else row["operating_cash_flow"]
            if is_repurchase:
                amount = str(-int(amount))  # Cash-flow statement outflow sign.
            return {
                "cik": company["cik"],
                "company": company["name"],
                "taxonomy": "us-gaap",
                "concept": concept,
                "label": "Payments for repurchases of common stock" if is_repurchase else "Net cash provided by operating activities",
                "value": amount,
                "unit": "USD",
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "fiscal_year": row["fiscal_year"],
                "form": "10-K",
                "filing_date": row["filing_date"],
                "accession_number": row["accession_number"],
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=PeriodResolver(),
        fact_retriever=FactRetriever(),
        company_resolver=CompanyResolver(),
    ).run(question)

    assert result.answer.formula_id == "Q10"
    assert Decimal(result.answer.result_value) == Decimal(
        reference_case["expected_current_ratio_percent"]
    )
    assert f"${int(current['share_repurchase_cash']):,}" in result.answer.text
    assert f"${int(prior['share_repurchase_cash']):,}" in result.answer.text
    assert "increased" in result.answer.text or "decreased" in result.answer.text or "unchanged" in result.answer.text
    assert len(result.answer.evidence) == 4


def test_q09_uses_matching_inventory_balances_and_exact_filing_narrative():
    question = "How did inventory change relative to revenue from FY2024 to FY2025, and what factors does management disclose?"
    plan = make_plan().model_copy(update={
        "original_question": question,
        "benchmark_id": "Q09",
        "metrics": [
            MetricRequest(name="total_revenue", role="primary", sources=["xbrl"]),
            MetricRequest(name="inventory", role="supporting", sources=["xbrl"]),
        ],
        "operation": "inventory_revenue_growth_comparison",
    })

    class Planner:
        def plan(self, _question):
            return plan

    class Facts:
        def get_fact(self, *, concept, end_date, **kwargs):
            value = FACTS[2024 if end_date == "2024-01-28" else 2025]
            if concept == "InventoryNet":
                value = {**value, "concept": concept, "label": "Inventory", "value": 5_282_000_000 if end_date == "2024-01-28" else 10_080_000_000, "start_date": None}
            return {**value, "concept": concept}

    accession = PERIODS[2025].accession_number
    filing_url = "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm"

    class Submissions:
        def get_filing_url(self, **_kwargs):
            return filing_url

    class Filings:
        submissions = Submissions()
        def get_filing(self, *, cik, accession_number, form):
            assert cik == CIK and accession_number == accession and form == "10-K"
            return {"primary_document": "nvda-20250126.htm", "html": "<html><body><p>Item 7. Management's Discussion and Analysis</p><p>Our expanding product portfolio may lead to increased inventory levels as demand changes.</p></body></html>"}

    result = FinSpectOrchestrator(
        planner=Planner(), normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=Facts(), company_resolver=FixtureCompanyResolver(),
        filing_retriever=Filings(),
        filing_parser=__import__("finspect.edgar.parser", fromlist=["FilingParser"]).FilingParser(),
        narrative_retriever=__import__("finspect.narrative_retriever", fromlist=["NarrativeRetriever"]).NarrativeRetriever(),
    ).run(question)

    assert result.answer.formula_id == "Q09"
    assert result.answer.result_unit == "percentage_points"
    assert "increased inventory levels" in result.answer.text
    assert filing_url in result.answer.text
    assert result.answer.limitations


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


_RECEIVABLES_MATRIX = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "data"
        / "fixtures"
        / "annual_receivables_reference_matrix.json"
    ).read_text(encoding="utf-8")
)["issuers"]
_RECEIVABLES_CASES = [
    (issuer, comparison)
    for issuer in _RECEIVABLES_MATRIX
    for comparison in issuer["comparisons"]
]


@pytest.mark.parametrize(
    ("issuer", "comparison"),
    _RECEIVABLES_CASES,
    ids=lambda parameter: parameter.get("company", {}).get("ticker")
    if isinstance(parameter, dict) and "company" in parameter
    else f"FY{parameter['prior_year']}-FY{parameter['current_year']}",
)
def test_q08_receivables_reference_matrix_runs_through_orchestrator(
    issuer, comparison
):
    company = issuer["company"]
    periods_by_year = {row["fiscal_year"]: row for row in issuer["periods"]}
    prior = periods_by_year[comparison["prior_year"]]
    current = periods_by_year[comparison["current_year"]]
    question = (
        f"How did accounts receivable growth compare with revenue growth for "
        f"{company['name']} from FY{prior['fiscal_year']} to FY{current['fiscal_year']}?"
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
        "operation": "growth_comparison",
        "metrics": [
            MetricRequest(name="accounts_receivable", role="primary", sources=["xbrl"]),
            MetricRequest(name="revenue", role="supporting", sources=["xbrl"]),
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
            is_receivables = concept == "AccountsReceivableNetCurrent"
            return {
                "cik": company["cik"], "company": company["name"],
                "taxonomy": "us-gaap", "concept": concept,
                "label": "Accounts receivable, net" if is_receivables else "Revenue",
                "value": row["receivables"] if is_receivables else row["revenue"],
                "unit": "USD", "start_date": None if is_receivables else row["start_date"],
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
        comparison["expected_growth_difference_percentage_points"]
    )
    assert result.answer.result_unit == "percentage_points"
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


def test_q12_retrieves_exact_annual_statement_of_equity_and_calculates_contribution():
    question = (
        "What were NVIDIA's principal changes in shareholders' equity during FY2025, "
        "and what percentage of ending equity did the largest component represent?"
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "company": CompanyRequest(name="NVIDIA", ticker="NVDA", cik=CIK),
        "period": PeriodRequest(
            period_label="FY2025",
            period_kind="annual",
            fiscal_year=2025,
            comparison_required=False,
        ),
        "benchmark_id": "Q12",
        "task_type": "calculation",
        "operation": "equity_component_contribution",
        "metrics": [
            MetricRequest(
                name="shareholders_equity", role="primary", sources=["financial_table"]
            ),
            MetricRequest(
                name="equity_components", role="supporting", sources=["financial_table"]
            ),
        ],
        "retrieval": RetrievalRequirements(sources=["financial_table"]),
        "answer": AnswerRequirements(include_formula=True, expected_output="percentage"),
    })

    class Planner:
        def plan(self, _question):
            return plan

    class Resolver:
        def resolve(self, **_kwargs):
            return {"name": "NVIDIA Corporation", "ticker": "NVDA", "cik": CIK}

    filing = {
        "cik": CIK,
        "form": "10-K",
        "filing_date": "2025-02-26",
        "report_date": "2025-01-26",
        "accession_number": "0001045810-25-000023",
        "primary_document": "nvda-20250126.htm",
        "html": """
        <table>
          <tr><th>(In millions, except per share data)</th><th>Jan 26, 2025</th><th>Jan 28, 2024</th></tr>
          <tr><td>Net income</td><td>72,880</td><td>29,760</td></tr>
          <tr><td>Other comprehensive income</td><td>1</td><td>70</td></tr>
          <tr><td>Issuance of common stock from stock plans</td><td>490</td><td>403</td></tr>
          <tr><td>Shares repurchased</td><td>(34,015)</td><td>(9,746)</td></tr>
          <tr><td>Cash dividends declared and paid</td><td>(834)</td><td>(395)</td></tr>
          <tr><td>Stock-based compensation</td><td>4,757</td><td>3,568</td></tr>
          <tr><td>Total shareholders' equity, ending balances</td><td>79,327</td><td>42,978</td></tr>
        </table>
        """,
    }

    class FilingRetriever:
        submissions = type("Submissions", (), {
            "get_filing_url": staticmethod(
                lambda **_kwargs: "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm"
            )
        })()

        def get_filing(self, *, cik, accession_number, form):
            assert cik == CIK
            assert accession_number == filing["accession_number"]
            assert form == "10-K"
            return filing

    class NoFacts:
        def get_fact(self, **_kwargs):
            raise AssertionError("Q12 should use the exact filing table, not XBRL guesses")

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=NoFacts(),
        company_resolver=Resolver(),
        filing_retriever=FilingRetriever(),
        filing_parser=FilingParser(),
    ).run(question)

    assert result.answer.formula_id == "Q12"
    assert Decimal(result.answer.result_value) == Decimal(
        "91.87288060811577394834041373"
    )
    assert "Net income" in result.answer.text
    assert "FY2025" in result.answer.text
    assert len(result.answer.evidence) == 7
    assert all(
        item.accession_number == filing["accession_number"]
        and item.source_url.endswith("nvda-20250126.htm")
        for item in result.answer.evidence
    )


def test_q12_rejects_wrong_filing_period_before_equity_extraction():
    question = "What were NVIDIA's principal equity changes during FY2025?"
    plan = make_plan().model_copy(update={
        "original_question": question,
        "company": CompanyRequest(name="NVIDIA", ticker="NVDA", cik=CIK),
        "period": PeriodRequest(
            period_label="FY2025", period_kind="annual", fiscal_year=2025
        ),
        "benchmark_id": "Q12",
        "operation": "equity_component_contribution",
        "metrics": [
            MetricRequest(name="shareholders_equity", role="primary", sources=["financial_table"]),
            MetricRequest(name="equity_components", role="supporting", sources=["financial_table"]),
        ],
        "retrieval": RetrievalRequirements(sources=["financial_table"]),
    })

    class Planner:
        def plan(self, _question):
            return plan

    class Resolver:
        def resolve(self, **_kwargs):
            return {"name": "NVIDIA Corporation", "ticker": "NVDA", "cik": CIK}

    class FilingRetriever:
        def get_filing(self, **_kwargs):
            return {
                "cik": CIK,
                "form": "10-K",
                "filing_date": "2025-02-26",
                "report_date": "2024-01-28",
                "accession_number": "0001045810-24-000029",
                "primary_document": "nvda-20240128.htm",
                "html": "<table></table>",
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=Resolver(),
        filing_retriever=FilingRetriever(),
        filing_parser=FilingParser(),
    ).run(question)

    assert result.answer.formula_id is None
    assert "does not match" in result.answer.text


def test_q12_exact_filing_pipeline_matches_all_six_issuer_period_references():
    matrix_path = (
        Path(__file__).parents[1]
        / "data"
        / "fixtures"
        / "annual_equity_allocation_reference_matrix.json"
    )
    references = json.loads(matrix_path.read_text(encoding="utf-8"))["cases"]
    assert len(references) == 6

    for reference in references:
        company = reference["company"]
        fiscal_year = reference["fiscal_year"]
        period = AnnualPeriod(
            fiscal_year=fiscal_year,
            start_date=reference["start_date"],
            end_date=reference["end_date"],
            form="10-K",
            concept="ShareholdersEquity",
            filing_date=reference["filing_date"],
            accession_number=reference["accession_number"],
        )
        rows = "".join(
            f"<tr><td>{item['label']}</td><td>{item['value']}</td></tr>"
            for item in reference["components"]
        )
        html = f"""
        <p>Statement of Shareholders’ Equity</p><p>(In millions)</p>
        <table>
          <tr><th>Fiscal year</th><th>{fiscal_year}</th></tr>
          {rows}
          <tr><td>Total shareholders’ equity, ending balances</td>
              <td>{reference['ending_equity']}</td></tr>
        </table>
        """
        question = (
            f"What were {company['name']}'s principal equity changes in FY{fiscal_year}, "
            "and what percent of ending equity did the largest change represent?"
        )
        plan = make_plan().model_copy(update={
            "original_question": question,
            "company": CompanyRequest(
                name=company["name"],
                ticker=company["ticker"],
                cik=company["cik"],
            ),
            "period": PeriodRequest(
                period_label=f"FY{fiscal_year}",
                period_kind="annual",
                fiscal_year=fiscal_year,
                comparison_required=False,
            ),
            "benchmark_id": "Q12",
            "operation": "equity_component_contribution",
            "metrics": [
                MetricRequest(
                    name="shareholders_equity",
                    role="primary",
                    sources=["financial_table"],
                ),
                MetricRequest(
                    name="equity_components",
                    role="supporting",
                    sources=["financial_table"],
                ),
            ],
            "retrieval": RetrievalRequirements(sources=["financial_table"]),
        })

        class Planner:
            def plan(self, _question):
                return plan

        class Resolver:
            def resolve(self, **_kwargs):
                return company

        class FilingRetriever:
            submissions = type("Submissions", (), {
                "get_filing_url": staticmethod(lambda **_kwargs: reference["source_url"])
            })()

            def get_filing(self, **_kwargs):
                return {
                    "cik": company["cik"],
                    "form": "10-K",
                    "filing_date": reference["filing_date"],
                    "report_date": reference["end_date"],
                    "accession_number": reference["accession_number"],
                    "primary_document": "reference-filing.htm",
                    "html": html,
                }

        class NoFacts:
            def get_fact(self, **_kwargs):
                raise AssertionError("Q12 should use the exact filing equity table")

        result = FinSpectOrchestrator(
            planner=Planner(),
            normalizer=normalize_query_plan,
            period_resolver=lambda _cik, _year: period,
            fact_retriever=NoFacts(),
            company_resolver=Resolver(),
            filing_retriever=FilingRetriever(),
        ).run(question)

        assert result.answer.formula_id == "Q12"
        assert result.answer.result_value == reference["expected_contribution_percent"]
        assert result.answer.evidence[-1].accession_number == reference["accession_number"]
        assert result.answer.evidence[-1].value == Decimal(reference["ending_equity"]) * 1_000_000


def test_q14_annual_cash_allocation_uses_four_period_matched_cash_facts():
    question = (
        "What proportion of NVIDIA's FY2025 operating cash flow was allocated "
        "to share repurchases, dividends, and capital expenditure?"
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "period": PeriodRequest(
            period_label="FY2025",
            period_kind="annual",
            fiscal_year=2025,
            comparison_required=False,
        ),
        "benchmark_id": "Q14",
        "operation": "cash_allocation",
        "metrics": [
            MetricRequest(name="share_repurchase_cash", role="supporting", sources=["xbrl"]),
            MetricRequest(name="dividends_paid", role="supporting", sources=["xbrl"]),
            MetricRequest(name="capital_expenditure", role="supporting", sources=["xbrl"]),
            MetricRequest(name="operating_cash_flow", role="primary", sources=["xbrl"]),
        ],
    })
    values = {
        "PaymentsForRepurchaseOfCommonStock": -33_706_000_000,
        "PaymentsOfDividendsCommonStock": -834_000_000,
        "PaymentsToAcquirePropertyPlantAndEquipment": -3_236_000_000,
        "NetCashProvidedByUsedInOperatingActivities": 64_089_000_000,
    }

    class Planner:
        def plan(self, _question):
            return plan

    class FactRetriever:
        def get_fact(self, *, concept, **kwargs):
            assert concept in values
            assert kwargs["end_date"] == "2025-01-26"
            assert kwargs["start_date"] == "2024-01-29"
            assert kwargs["accession_number"] == PERIODS[2025].accession_number
            return {
                **FACTS[2025],
                "concept": concept,
                "label": concept,
                "value": values[concept],
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FactRetriever(),
        company_resolver=FixtureCompanyResolver(),
    ).run(question)

    expected = (
        Decimal("33706000000") + Decimal("834000000") + Decimal("3236000000")
    ) / Decimal("64089000000") * Decimal("100")
    assert result.answer.formula_id == "Q14"
    assert Decimal(result.answer.result_value) == expected
    assert len(result.answer.evidence) == 4
    assert {fact.accession_number for fact in result.answer.evidence} == {
        PERIODS[2025].accession_number
    }


def test_q14_cash_allocation_pipeline_matches_six_annual_references():
    matrix_path = (
        Path(__file__).parents[1]
        / "data"
        / "fixtures"
        / "annual_cash_allocation_reference_matrix.json"
    )
    references = json.loads(matrix_path.read_text(encoding="utf-8"))["cases"]
    concept_by_metric = {
        "share_repurchase_cash": "PaymentsForRepurchaseOfCommonStock",
        "dividends_paid": "PaymentsOfDividendsCommonStock",
        "capital_expenditure": "PaymentsToAcquirePropertyPlantAndEquipment",
        "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
    }

    for reference in references:
        company = reference["company"]
        year = reference["fiscal_year"]
        period = AnnualPeriod(
            fiscal_year=year,
            start_date=reference["start_date"],
            end_date=reference["end_date"],
            form="10-K",
            concept="Revenues",
            filing_date=reference["filing_date"],
            accession_number=reference["accession_number"],
        )
        concept_values = {
            concept_by_metric["share_repurchase_cash"]: -int(reference["share_repurchase_cash"]),
            concept_by_metric["dividends_paid"]: -int(reference["dividends_paid"]),
            concept_by_metric["capital_expenditure"]: -int(reference["capital_expenditure"]),
            concept_by_metric["operating_cash_flow"]: int(reference["operating_cash_flow"]),
        }
        question = (
            f"What proportion of {company['name']}'s FY{year} operating cash flow "
            "was allocated to shareholder returns and capital expenditure?"
        )
        plan = make_plan().model_copy(update={
            "original_question": question,
            "company": CompanyRequest(**company),
            "period": PeriodRequest(
                period_label=f"FY{year}",
                period_kind="annual",
                fiscal_year=year,
                comparison_required=False,
            ),
            "benchmark_id": "Q14",
            "operation": "cash_allocation",
            "metrics": [
                MetricRequest(name=name, role="supporting", sources=["xbrl"])
                for name in concept_by_metric
            ],
        })

        class Planner:
            def plan(self, _question):
                return plan

        class CompanyResolver:
            def resolve(self, **_kwargs):
                return company

        class FactRetriever:
            def get_fact(self, *, concept, **_kwargs):
                return {
                    "cik": company["cik"],
                    "company": company["name"],
                    "taxonomy": "us-gaap",
                    "concept": concept,
                    "label": concept,
                    "value": concept_values[concept],
                    "unit": "USD",
                    "start_date": reference["start_date"],
                    "end_date": reference["end_date"],
                    "fiscal_year": year,
                    "form": "10-K",
                    "filing_date": reference["filing_date"],
                    "accession_number": reference["accession_number"],
                }

        result = FinSpectOrchestrator(
            planner=Planner(),
            normalizer=normalize_query_plan,
            period_resolver=lambda _cik, _year: period,
            fact_retriever=FactRetriever(),
            company_resolver=CompanyResolver(),
        ).run(question)

        assert result.answer.formula_id == "Q14"
        assert result.answer.result_value == reference["expected_cash_allocation_percent"]
        assert "capital expenditure" in result.answer.text.lower()
        assert any("cash-flow statement classification" in note for note in result.answer.limitations)
        assert len(result.answer.evidence) == 4
        assert {item.accession_number for item in result.answer.evidence} == {
            reference["accession_number"]
        }


def test_q06_equity_rollforward_matches_period_balances_and_current_statement():
    question = (
        "How did NVIDIA's shareholders' equity change during FY2025, "
        "and what were the principal disclosed components?"
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "period": PeriodRequest(
            period_label="FY2025",
            period_kind="annual",
            fiscal_year=2025,
            comparison_required=False,
        ),
        "benchmark_id": "Q06",
        "operation": "balance_change",
        "metrics": [
            MetricRequest(name="shareholders_equity", role="primary", sources=["financial_table"]),
            MetricRequest(name="equity_components", role="supporting", sources=["financial_table"]),
        ],
    })
    equity_values = {
        "2024-01-28": (42_978_000_000, PERIODS[2024]),
        "2025-01-26": (79_327_000_000, PERIODS[2025]),
    }
    html = """
    <p>(In millions)</p><table>
      <tr><td>Balances as of Jan 28, 2024</td><td>42,978</td></tr>
      <tr><td>Net income</td><td>72,880</td></tr>
      <tr><td>Other comprehensive income</td><td>1</td></tr>
      <tr><td>Shares repurchased</td><td>(34,015)</td></tr>
      <tr><td>Cash dividends declared and paid</td><td>(834)</td></tr>
      <tr><td>Stock-based compensation</td><td>4,757</td></tr>
      <tr><td>Balances as of Jan 26, 2025</td><td>79,327</td></tr>
    </table>
    """

    class Planner:
        def plan(self, _question):
            return plan

    class FilingRetriever:
        submissions = type("Submissions", (), {
            "get_filing_url": staticmethod(lambda **_kwargs: "https://www.sec.gov/Archives/edgar/data/1045810/current.htm")
        })()

        def get_filing(self, **_kwargs):
            return {
                "cik": CIK,
                "form": "10-K",
                "filing_date": PERIODS[2025].filing_date,
                "report_date": PERIODS[2025].end_date,
                "accession_number": PERIODS[2025].accession_number,
                "primary_document": "nvda-20250126.htm",
                "html": html,
            }

    class EquityFactRetriever:
        def get_fact(self, *, end_date, **kwargs):
            assert kwargs["concept"] == "StockholdersEquity"
            value, source_period = equity_values[end_date]
            assert kwargs["accession_number"] == source_period.accession_number
            return {
                "cik": CIK,
                "company": "NVIDIA Corporation",
                "taxonomy": "us-gaap",
                "concept": "StockholdersEquity",
                "label": "Stockholders’ equity",
                "value": value,
                "unit": "USD",
                "start_date": None,
                "end_date": end_date,
                "fiscal_year": source_period.fiscal_year,
                "form": "10-K",
                "filing_date": source_period.filing_date,
                "accession_number": source_period.accession_number,
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=EquityFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
        filing_retriever=FilingRetriever(),
    ).run(question)

    assert result.answer.formula_id == "Q06"
    assert Decimal(result.answer.result_value) == Decimal("36349000000")
    assert "increased by $36,349,000,000" in result.answer.text
    assert "Net income" in result.answer.text
    assert len(result.answer.evidence) == 7


def test_q06_equity_rollforward_pipeline_matches_six_reference_cases():
    root = Path(__file__).parents[1]
    references = json.loads(
        (root / "data/fixtures/annual_equity_rollforward_reference_matrix.json")
        .read_text(encoding="utf-8")
    )["cases"]
    equity_references = json.loads(
        (root / "data/fixtures/annual_equity_allocation_reference_matrix.json")
        .read_text(encoding="utf-8")
    )["cases"]
    period_rows = json.loads(
        (root / "data/fixtures/annual_share_repurchase_reference_matrix.json")
        .read_text(encoding="utf-8")
    )["cases"]
    periods_by_ticker = {}
    for item in period_rows:
        ticker = item["company"]["ticker"]
        for row in item["periods"]:
            periods_by_ticker.setdefault(ticker, {})[row["fiscal_year"]] = AnnualPeriod(
                fiscal_year=row["fiscal_year"],
                start_date=row["start_date"],
                end_date=row["end_date"],
                form="10-K",
                concept="Revenues",
                filing_date=row["filing_date"],
                accession_number=row["accession_number"],
            )

    for reference in references:
        company = reference["company"]
        ticker = company["ticker"]
        year = reference["fiscal_year"]
        period_map = periods_by_ticker[ticker]
        prior_period = period_map[year - 1]
        current_period = period_map[year]
        q12_reference = next(
            row for row in equity_references
            if row["company"]["ticker"] == ticker and row["fiscal_year"] == year
        )
        component_rows = "".join(
            f"<tr><td>{row['label']}</td><td>{row['value']}</td></tr>"
            for row in q12_reference["components"]
        )
        html = f"""
        <p>Statement of Shareholders’ Equity</p><p>(In millions)</p>
        <table>
          <tr><td>Fiscal Year</td><td>{year}</td></tr>
          {component_rows}
          <tr><td>Total shareholders’ equity, ending balances</td>
              <td>{q12_reference['ending_equity']}</td></tr>
        </table>
        """
        periods_by_end = {
            prior_period.end_date: (
                Decimal(reference["beginning_equity"]), prior_period
            ),
            current_period.end_date: (
                Decimal(reference["ending_equity"]), current_period
            ),
        }
        question = (
            f"How did {company['name']}'s shareholders' equity change during FY{year}, "
            "and what were the principal disclosed components?"
        )
        plan = make_plan().model_copy(update={
            "original_question": question,
            "company": CompanyRequest(**company),
            "period": PeriodRequest(
                period_label=f"FY{year}",
                period_kind="annual",
                fiscal_year=year,
                comparison_required=False,
            ),
            "benchmark_id": "Q06",
            "operation": "balance_change",
            "metrics": [
                MetricRequest(name="shareholders_equity", role="primary", sources=["financial_table"]),
                MetricRequest(name="equity_components", role="supporting", sources=["financial_table"]),
            ],
        })

        class Planner:
            def plan(self, _question):
                return plan

        class CompanyResolver:
            def resolve(self, **_kwargs):
                return company

        class FilingRetriever:
            submissions = type("Submissions", (), {
                "get_filing_url": staticmethod(lambda **_kwargs: reference["source_url"])
            })()

            def get_filing(self, **_kwargs):
                return {
                    "cik": company["cik"],
                    "form": "10-K",
                    "filing_date": reference["filing_date"],
                    "report_date": reference["end_date"],
                    "accession_number": reference["accession_number"],
                    "primary_document": "reference-filing.htm",
                    "html": html,
                }

        class FactRetriever:
            def get_fact(self, *, end_date, **kwargs):
                assert kwargs["concept"] == "StockholdersEquity"
                value, source_period = periods_by_end[end_date]
                assert kwargs["accession_number"] == source_period.accession_number
                return {
                    "cik": company["cik"],
                    "company": company["name"],
                    "taxonomy": "us-gaap",
                    "concept": "StockholdersEquity",
                    "label": "Stockholders’ equity",
                    "value": value,
                    "unit": "USD",
                    "start_date": None,
                    "end_date": end_date,
                    "fiscal_year": source_period.fiscal_year,
                    "form": "10-K",
                    "filing_date": source_period.filing_date,
                    "accession_number": source_period.accession_number,
                }

        result = FinSpectOrchestrator(
            planner=Planner(),
            normalizer=normalize_query_plan,
            period_resolver=lambda _cik, fiscal_year: period_map[fiscal_year],
            fact_retriever=FactRetriever(),
            company_resolver=CompanyResolver(),
            filing_retriever=FilingRetriever(),
        ).run(question)

        assert result.answer.formula_id == "Q06"
        assert result.answer.result_value == reference["expected_equity_change"]
        assert result.answer.evidence[-1].accession_number == reference["accession_number"]
        assert result.answer.evidence[-1].value == Decimal(reference["ending_equity"])


def test_q16_regulatory_risk_uses_item_1a_excerpt_from_exact_10k():
    question = (
        "What export-control and trade risks did NVIDIA identify in FY2025, "
        "and which products or markets could be affected?"
    )
    plan = make_plan().model_copy(update={
        "original_question": question,
        "period": PeriodRequest(
            period_label="FY2025",
            period_kind="annual",
            fiscal_year=2025,
            comparison_required=False,
        ),
        "benchmark_id": "Q16",
        "task_type": "disclosure_analysis",
        "operation": "regulatory_risk_analysis",
        "metrics": [
            MetricRequest(
                name="regulatory_risks", role="primary", sources=["risk_factors"]
            )
        ],
        "retrieval": RetrievalRequirements(sources=["risk_factors"]),
        "answer": AnswerRequirements(expected_output="text"),
    })
    html = """
    <p>ITEM 1. BUSINESS</p>
    <p>We develop and sell GPUs, networking products, and cloud services to customers around the world.</p>
    <p>ITEM 1A. RISK FACTORS</p>
    <p>Export controls targeting GPUs and semiconductors associated with AI may restrict our ability to export products and services, disrupt supply and distribution, and reduce demand in China and other markets.</p>
    """

    class Planner:
        def plan(self, _question):
            return plan

    class FilingRetriever:
        submissions = type("Submissions", (), {
            "get_filing_url": staticmethod(lambda **_kwargs: "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm")
        })()

        def get_filing(self, **_kwargs):
            return {
                "cik": CIK,
                "form": "10-K",
                "filing_date": PERIODS[2025].filing_date,
                "report_date": PERIODS[2025].end_date,
                "accession_number": PERIODS[2025].accession_number,
                "primary_document": "nvda-20250126.htm",
                "html": html,
            }

    result = FinSpectOrchestrator(
        planner=Planner(),
        normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
        filing_retriever=FilingRetriever(),
        filing_parser=FilingParser(),
        narrative_retriever=NarrativeRetriever(),
    ).run(question)

    assert result.answer.formula_id is None
    assert result.answer.result_value is None
    assert result.answer.evidence
    assert all(item.unit == "filing excerpt" for item in result.answer.evidence)
    assert all(item.accession_number == PERIODS[2025].accession_number for item in result.answer.evidence)
    assert "export controls" in result.answer.text.lower()
    assert "supply and distribution" in result.answer.text.lower()
    assert "nvda-20250126.htm" in result.answer.text


def test_q17_geographic_revenue_uses_exact_10k_and_reports_classification_caveat():
    question = "What share of NVIDIA's FY2025 revenue came from its largest geographic exposure?"
    plan = make_plan().model_copy(update={
        "original_question": question,
        "period": PeriodRequest(
            period_label="FY2025", period_kind="annual", fiscal_year=2025,
            comparison_required=False,
        ),
        "benchmark_id": "Q17",
        "task_type": "disclosure_analysis",
        "operation": "geographic_exposure",
        "metrics": [MetricRequest(
            name="geographic_revenue", role="primary", sources=["financial_table"]
        )],
        "retrieval": RetrievalRequirements(sources=["financial_table"]),
        "answer": AnswerRequirements(expected_output="text"),
    })
    html = """
    <p>Revenue by geographic area is based upon customer billing location.</p>
    <table>
      <tr><th>Area</th><th>2025</th></tr>
      <tr><td>United States</td><td>60</td></tr>
      <tr><td>Singapore</td><td>25</td></tr>
      <tr><td>Taiwan</td><td>15</td></tr>
      <tr><td>Total revenue</td><td>100</td></tr>
    </table>
    <p>Shipping location may be different from customer billing location.</p>
    """

    class Planner:
        def plan(self, _question):
            return plan

    class FilingRetriever:
        submissions = type("Submissions", (), {
            "get_filing_url": staticmethod(lambda **_kwargs: "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm")
        })()

        def get_filing(self, *, cik, accession_number, form):
            assert cik == CIK
            assert accession_number == PERIODS[2025].accession_number
            assert form == "10-K"
            return {
                "cik": CIK, "form": "10-K",
                "filing_date": PERIODS[2025].filing_date,
                "report_date": PERIODS[2025].end_date,
                "accession_number": PERIODS[2025].accession_number,
                "primary_document": "nvda-20250126.htm", "html": html,
            }

    result = FinSpectOrchestrator(
        planner=Planner(), normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
        filing_retriever=FilingRetriever(),
    ).run(question)

    assert result.answer.result_value == "60.00"
    assert result.answer.result_unit == "percent"
    assert "United States" in result.answer.text
    assert any("billing location" in item for item in result.answer.limitations)
    assert any("Shipping location may be different" in item for item in result.answer.limitations)
    assert result.facts[0]["accession_number"] == PERIODS[2025].accession_number
    assert "nvda-20250126.htm" in result.facts[0]["source_url"]


def test_q17_pipeline_matches_all_six_issuer_period_references():
    root = Path(__file__).parents[1]
    references = json.loads(
        (root / "data/fixtures/annual_geographic_revenue_reference_matrix.json")
        .read_text(encoding="utf-8")
    )["cases"]

    for reference in references:
        company = reference["company"]
        year = reference["fiscal_year"]
        question = f"What share of {company['name']}'s FY{year} revenue came from its largest geographic region?"
        plan = make_plan().model_copy(update={
            "original_question": question,
            "company": CompanyRequest(**company),
            "period": PeriodRequest(
                period_label=f"FY{year}", period_kind="annual", fiscal_year=year,
                comparison_required=False,
            ),
            "benchmark_id": "Q17",
            "task_type": "disclosure_analysis",
            "operation": "geographic_exposure",
            "metrics": [MetricRequest(
                name="geographic_revenue", role="primary", sources=["financial_table"]
            )],
            "retrieval": RetrievalRequirements(sources=["financial_table"]),
            "answer": AnswerRequirements(expected_output="text"),
        })
        geographic_rows = "".join(
            f"<tr><td>{label}</td><td>{value}</td></tr>"
            for label, value in reference["geographic_revenue"].items()
        )
        basis_text = {
            "billing_location": "Revenue by geographic area is based upon customer billing location.",
            "customer_location": "Revenue classified by the major geographic areas in which customers were located.",
            "management_defined": "Reportable segments consist of the following geographic areas.",
        }[reference["classification_basis"]]
        caveat_text = {
            "billing_location": "End customer location may be different from the customer billing location.",
            "customer_location": "Includes billings to OEMs and multinational organizations when it is impracticable to determine geographic source.",
            "management_defined": "Net sales for geographic segments are generally based on customers' location.",
        }[reference["classification_basis"]]
        html = (
            f"<p>{basis_text}</p><table><tr><th>Area</th><th>Year Ended {year}</th></tr>"
            f"{geographic_rows}<tr><td>Total revenue</td><td>{reference['total_revenue']}</td></tr></table>"
            f"<p>{caveat_text}</p>"
        )
        period = AnnualPeriod(
            fiscal_year=year,
            start_date=reference["start_date"],
            end_date=reference["end_date"],
            filing_date=reference["filing_date"],
            accession_number=reference["accession_number"],
        )

        class Planner:
            def plan(self, _question):
                return plan

        class CompanyResolver:
            def resolve(self, **_kwargs):
                return company

        class FilingRetriever:
            submissions = type("Submissions", (), {
                "get_filing_url": staticmethod(lambda **_kwargs: reference["source_url"])
            })()

            def get_filing(self, **_kwargs):
                return {
                    "cik": company["cik"], "form": "10-K",
                    "filing_date": reference["filing_date"],
                    "report_date": reference["end_date"],
                    "accession_number": reference["accession_number"],
                    "primary_document": reference["source_url"].rsplit("/", 1)[-1],
                    "html": html,
                }

        result = FinSpectOrchestrator(
            planner=Planner(), normalizer=normalize_query_plan,
            period_resolver=lambda _cik, _year: period,
            fact_retriever=FixtureFactRetriever(),
            company_resolver=CompanyResolver(), filing_retriever=FilingRetriever(),
        ).run(question)

        assert result.answer.result_value == reference["share_percent"]
        assert result.answer.result_unit == "percent"
        assert result.facts[0]["classification_basis"] == reference["classification_basis"]
        assert result.answer.limitations
        assert result.facts[0]["largest_geography"] == reference["largest_geography"]
        assert result.facts[0]["accession_number"] == reference["accession_number"]


def test_q16_exact_filing_pipeline_matches_six_issuer_period_references():
    root = Path(__file__).parents[1]
    references = json.loads(
        (root / "data/fixtures/annual_regulatory_risk_reference_matrix.json")
        .read_text(encoding="utf-8")
    )["cases"]
    period_rows = json.loads(
        (root / "data/fixtures/annual_share_repurchase_reference_matrix.json")
        .read_text(encoding="utf-8")
    )["cases"]
    periods_by_ticker = {}
    for item in period_rows:
        ticker = item["company"]["ticker"]
        for row in item["periods"]:
            periods_by_ticker.setdefault(ticker, {})[row["fiscal_year"]] = AnnualPeriod(
                fiscal_year=row["fiscal_year"],
                start_date=row["start_date"],
                end_date=row["end_date"],
                form="10-K",
                concept="Revenues",
                filing_date=row["filing_date"],
                accession_number=row["accession_number"],
            )

    for reference in references:
        company = reference["company"]
        period = periods_by_ticker[company["ticker"]][reference["fiscal_year"]]
        question = (
            f"What regulatory, export-control, or trade risks did {company['name']} "
            f"identify in FY{reference['fiscal_year']}, and what products or markets could be affected?"
        )
        plan = make_plan().model_copy(update={
            "original_question": question,
            "company": CompanyRequest(**company),
            "period": PeriodRequest(
                period_label=f"FY{reference['fiscal_year']}",
                period_kind="annual",
                fiscal_year=reference["fiscal_year"],
                comparison_required=False,
            ),
            "benchmark_id": "Q16",
            "task_type": "disclosure_analysis",
            "operation": "regulatory_risk_analysis",
            "metrics": [
                MetricRequest(
                    name="regulatory_risks", role="primary", sources=["risk_factors"]
                )
            ],
            "retrieval": RetrievalRequirements(sources=["risk_factors"]),
            "answer": AnswerRequirements(expected_output="text"),
        })
        html = (
            "<p>ITEM 1A. RISK FACTORS</p><p>"
            + reference["reference_excerpt"]
            + "</p>"
        )

        class Planner:
            def plan(self, _question):
                return plan

        class CompanyResolver:
            def resolve(self, **_kwargs):
                return company

        class FilingRetriever:
            submissions = type("Submissions", (), {
                "get_filing_url": staticmethod(lambda **_kwargs: reference["source_url"])
            })()

            def get_filing(self, **_kwargs):
                return {
                    "cik": company["cik"],
                    "form": "10-K",
                    "filing_date": reference["filing_date"],
                    "report_date": reference["end_date"],
                    "accession_number": reference["accession_number"],
                    "primary_document": reference["source_url"].rsplit("/", 1)[-1],
                    "html": html,
                }

        result = FinSpectOrchestrator(
            planner=Planner(),
            normalizer=normalize_query_plan,
            period_resolver=lambda _cik, _year: period,
            fact_retriever=FixtureFactRetriever(),
            company_resolver=CompanyResolver(),
            filing_retriever=FilingRetriever(),
            filing_parser=FilingParser(),
            narrative_retriever=NarrativeRetriever(),
        ).run(question)

        assert result.answer.formula_id is None
        assert result.answer.evidence
        assert all(
            item.accession_number == reference["accession_number"]
            and item.source_url == reference["source_url"]
            for item in result.answer.evidence
        )
        assert any(reference["reference_excerpt"] in str(item.value) for item in result.answer.evidence)


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
        if number not in {2, 3, 4, 5, 7, 8, 9, 10, 11, 13}
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


def test_q02_retrieves_exact_10k_and_reports_largest_segment_contribution():
    from types import SimpleNamespace

    plan = QueryPlan(
        original_question="Which reportable segment drove revenue growth?",
        company=CompanyRequest(name="NVIDIA", ticker="NVDA", cik=CIK),
        period=PeriodRequest(
            period_kind="annual", fiscal_year=2025,
            comparison_required=True, comparison_period="FY2024",
        ),
        benchmark_id="Q02", task_type="calculation",
        metrics=[
            MetricRequest(name="total_revenue", role="primary", sources=["segment_disclosure"]),
            MetricRequest(name="segment_revenue", role="primary", sources=["segment_disclosure"]),
        ],
        operation="growth_contribution", retrieval={"sources": ["segment_disclosure"]},
    )
    html = """
    <p>Reportable segment revenue (in millions)</p>
    <table><tr><th></th><th>2025</th><th>2024</th></tr>
    <tr><td>Segment A</td><td>200</td><td>100</td></tr>
    <tr><td>Segment B</td><td>100</td><td>100</td></tr>
    <tr><td>Total net sales</td><td>300</td><td>200</td></tr></table>
    """
    url = "https://www.sec.gov/Archives/edgar/data/example.htm"

    class ExactFilingRetriever:
        submissions = SimpleNamespace(
            get_filing_url=lambda **_kwargs: url,
        )

        def get_filing(self, *, cik, accession_number, form):
            assert cik == CIK
            assert accession_number == PERIODS[2025].accession_number
            assert form == "10-K"
            return {
                "form": "10-K", "cik": CIK,
                "accession_number": PERIODS[2025].accession_number,
                "filing_date": PERIODS[2025].filing_date,
                "report_date": PERIODS[2025].end_date,
                "primary_document": "nvda-20250126.htm", "html": html,
            }

    class Q02Planner:
        def plan(self, _question):
            return plan

    orchestrator = FinSpectOrchestrator(
        planner=Q02Planner(), normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
        filing_retriever=ExactFilingRetriever(),
    )
    result = orchestrator.run(plan.original_question)

    assert result.answer.formula_id == "Q02"
    assert result.answer.result_value == "100"
    assert "Segment A" in result.answer.text
    assert result.facts[0]["accession_number"] == PERIODS[2025].accession_number
    assert all(item.source_url == url for item in result.answer.evidence)


def test_q04_retrieves_exact_10k_and_reports_largest_expense_contribution():
    from types import SimpleNamespace

    plan = QueryPlan(
        original_question="Which expense category drove operating expense growth?",
        company=CompanyRequest(name="NVIDIA", ticker="NVDA", cik=CIK),
        period=PeriodRequest(
            period_kind="annual", fiscal_year=2025,
            comparison_required=True, comparison_period="FY2024",
        ),
        benchmark_id="Q04", task_type="calculation",
        metrics=[
            MetricRequest(name="operating_expenses", role="primary", sources=["financial_table"]),
            MetricRequest(name="expense_category", role="primary", sources=["financial_table"]),
        ],
        operation="expense_growth_contribution",
        retrieval={"sources": ["financial_table"]},
    )
    html = """
    <table>
      <tr><th></th><th>2025</th><th>2024</th></tr>
      <tr><td>Gross margin</td><td>194</td><td>171</td></tr>
      <tr><td>Research and development</td><td>32</td><td>29</td></tr>
      <tr><td>Sales and marketing</td><td>25</td><td>24</td></tr>
      <tr><td>General and administrative</td><td>7</td><td>8</td></tr>
      <tr><td>Operating income</td><td>130</td><td>110</td></tr>
    </table>
    """
    url = "https://www.sec.gov/Archives/edgar/data/example.htm"

    class ExactFilingRetriever:
        submissions = SimpleNamespace(get_filing_url=lambda **_kwargs: url)

        def get_filing(self, *, cik, accession_number, form):
            assert cik == CIK
            assert accession_number == PERIODS[2025].accession_number
            assert form == "10-K"
            return {
                "form": "10-K", "cik": CIK,
                "accession_number": PERIODS[2025].accession_number,
                "filing_date": PERIODS[2025].filing_date,
                "report_date": PERIODS[2025].end_date,
                "primary_document": "nvda-20250126.htm", "html": html,
            }

    class Q04Planner:
        def plan(self, _question):
            return plan

    orchestrator = FinSpectOrchestrator(
        planner=Q04Planner(), normalizer=normalize_query_plan,
        period_resolver=lambda _cik, year: PERIODS[year],
        fact_retriever=FixtureFactRetriever(),
        company_resolver=FixtureCompanyResolver(),
        filing_retriever=ExactFilingRetriever(),
    )
    result = orchestrator.run(plan.original_question)

    assert result.answer.formula_id == "Q04"
    assert result.answer.result_value == "100"
    assert "Research and development" in result.answer.text
    assert result.facts[0]["total_method"] == "gross margin minus operating income"
    assert all(item.source_url == url for item in result.answer.evidence)
