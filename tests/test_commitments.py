from decimal import Decimal

import pytest

from finspect.edgar.commitments import (
    CommitmentScheduleError,
    CommitmentScheduleExtractor,
)
from finspect.orchestrator import AnnualPeriod, FinSpectOrchestrator
from finspect.plan_normalizer import normalize_query_plan
from finspect.query_planner import (
    CompanyRequest, MetricRequest, PeriodRequest, QueryPlan,
    RetrievalRequirements,
)


def test_extracts_annual_bucket_and_total_from_generic_sec_schedule():
    html = """
    <p>Contractual obligations (in millions)</p>
    <table>
      <tr><th></th><th>2026</th><th>Thereafter</th><th>Total</th></tr>
      <tr><td>Construction commitments</td><td>26,859</td><td>5,290</td><td>32,149</td></tr>
      <tr><td>Purchase commitments</td><td>103,940</td><td>6,013</td><td>109,953</td></tr>
      <tr><td>Total</td><td>148,106</td><td>248,939</td><td>397,045</td></tr>
    </table>
    """
    result = CommitmentScheduleExtractor().extract(html, next_fiscal_year=2026)
    assert result.total_commitments == Decimal("397045")
    assert result.next_year_commitments == Decimal("148106")
    assert result.unit == "USD millions"


def test_extracts_less_than_one_year_bucket_and_accounting_zero():
    html = """
    <table>
      <tr><th>Contractual obligations</th><th>Total</th><th>Less than 1 year</th></tr>
      <tr><td>Operating leases</td><td>100</td><td>20</td></tr>
      <tr><td>Purchase commitments</td><td>50</td><td>—</td></tr>
      <tr><td>Total</td><td>150</td><td>20</td></tr>
    </table>
    """
    result = CommitmentScheduleExtractor().extract(html, next_fiscal_year=2026)
    assert result.total_commitments == Decimal("150")
    assert result.next_year_commitments == Decimal("20")


def test_extracts_fiscal_year_rows_followed_by_total():
    html = """
    <p>Total future purchase commitments (in millions)</p>
    <table>
      <tr><td>Commitments</td><td>(In millions)</td></tr>
      <tr><td>Fiscal Year:</td><td></td></tr>
      <tr><td>2026</td><td>35,727</td></tr>
      <tr><td>2027</td><td>3,666</td></tr>
      <tr><td>2028</td><td>2,992</td></tr>
      <tr><td>Total</td><td>45,079</td></tr>
    </table>
    """
    result = CommitmentScheduleExtractor().extract(html, next_fiscal_year=2026)
    assert result.total_commitments == Decimal("45079")
    assert result.next_year_commitments == Decimal("35727")


def test_handles_sec_currency_symbol_columns_repeated_under_spanning_headers():
    html = """
    <table>
      <tr><td>(In millions)</td><td></td><td>2026</td><td>2026</td><td></td><td>Thereafter</td><td>Thereafter</td><td>Total</td><td>Total</td></tr>
      <tr><td>Purchase commitments</td><td></td><td>$</td><td>103,940</td><td></td><td>$</td><td>6,013</td><td>$</td><td>109,953</td></tr>
      <tr><td>Total</td><td></td><td>$</td><td>148,106</td><td></td><td>$</td><td>248,939</td><td>$</td><td>397,045</td></tr>
    </table>
    """
    result = CommitmentScheduleExtractor().extract(html, next_fiscal_year=2026)
    assert result.total_commitments == Decimal("397045")
    assert result.next_year_commitments == Decimal("148106")


def test_year_row_parser_skips_repeated_labels_and_currency_symbols():
    html = """
    <table>
      <tr><td></td><td></td><td></td><td>Commitments</td><td>Commitments</td></tr>
      <tr><td>Fiscal Year:</td><td>Fiscal Year:</td><td>Fiscal Year:</td><td></td><td></td></tr>
      <tr><td>2026</td><td>2026</td><td>2026</td><td>$</td><td>35,727</td></tr>
      <tr><td>2027</td><td>2027</td><td>2027</td><td></td><td>3,666</td></tr>
      <tr><td>Total</td><td>Total</td><td>Total</td><td>$</td><td>45,079</td></tr>
    </table>
    """
    result = CommitmentScheduleExtractor().extract(html, next_fiscal_year=2026)
    assert result.total_commitments == Decimal("45079")
    assert result.next_year_commitments == Decimal("35727")


def test_refuses_multiple_schedules_instead_of_double_counting():
    table = """<table><tr><th>Contractual obligations</th><th>Total</th><th>Less than 1 year</th></tr>
    <tr><td>Total</td><td>100</td><td>20</td></tr></table>"""
    with pytest.raises(CommitmentScheduleError, match="Multiple"):
        CommitmentScheduleExtractor().extract(table + table, next_fiscal_year=2026)


def test_refuses_prose_only_or_missing_next_year_amount():
    with pytest.raises(CommitmentScheduleError):
        CommitmentScheduleExtractor().extract(
            "<p>We have future commitments of $100 million.</p>",
            next_fiscal_year=2026,
        )


def test_q15_pipeline_uses_exact_filing_and_period_matched_liquidity():
    cik = "0000789019"
    period = AnnualPeriod(
        fiscal_year=2025, start_date="2024-07-01", end_date="2025-06-30",
        form="10-K", filing_date="2025-07-30",
        accession_number="0000950170-25-100235",
    )
    question = "As of FY2025, what are Microsoft's commitments due in the next fiscal year compared with liquid resources?"
    plan = QueryPlan(
        original_question=question,
        company=CompanyRequest(name="Microsoft", ticker="MSFT", cik=cik),
        period=PeriodRequest(period_kind="annual", fiscal_year=2025),
        benchmark_id="Q15", task_type="calculation",
        metrics=[
            MetricRequest(name=name, role="primary", sources=[source])
            for name, source in (
                ("future_commitments", "financial_table"),
                ("near_term_commitments", "financial_table"),
                ("cash_and_cash_equivalents", "xbrl"),
                ("short_term_investments", "xbrl"),
            )
        ],
        operation="commitment_liquidity",
        retrieval=RetrievalRequirements(sources=["financial_table", "xbrl"]),
    )
    html = """
    <table><tr><td>(In millions)</td><td></td><td>2026</td><td>2026</td><td>Thereafter</td><td>Thereafter</td><td>Total</td><td>Total</td></tr>
    <tr><td>Purchase commitments</td><td></td><td>$</td><td>103,940</td><td>$</td><td>6,013</td><td>$</td><td>109,953</td></tr>
    <tr><td>Total</td><td></td><td>$</td><td>148,106</td><td>$</td><td>248,939</td><td>$</td><td>397,045</td></tr></table>
    """

    class FilingRetriever:
        submissions = type("Submissions", (), {
            "get_filing_url": staticmethod(lambda **_: "https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm")
        })()

        def get_filing(self, **_):
            return {"cik": cik, "form": "10-K", "filing_date": period.filing_date,
                    "report_date": period.end_date, "accession_number": period.accession_number,
                    "primary_document": "msft-20250630.htm", "html": html}

    class FactRetriever:
        def get_fact(self, *, concept, **_):
            value = 30_242_000_000 if concept == "CashAndCashEquivalentsAtCarryingValue" else 64_323_000_000
            return {"cik": cik, "company": "Microsoft Corporation", "taxonomy": "us-gaap",
                    "concept": concept, "value": value, "unit": "USD", "start_date": None,
                    "end_date": period.end_date, "form": "10-K", "filing_date": period.filing_date,
                    "accession_number": period.accession_number}

    class CompanyResolver:
        def resolve(self, **_):
            return {"name": "Microsoft Corporation", "ticker": "MSFT", "cik": cik}

    result = FinSpectOrchestrator(
        planner=type("Planner", (), {"plan": staticmethod(lambda _: plan)})(),
        normalizer=normalize_query_plan,
        period_resolver=lambda *_: period,
        fact_retriever=FactRetriever(), company_resolver=CompanyResolver(),
        filing_retriever=FilingRetriever(),
    ).run(question)

    assert result.answer.formula_id == "Q15"
    assert result.answer.result_unit == "x"
    assert "37.30%" in result.answer.text
    assert "0.64 times" in result.answer.text
    assert all(item.accession_number == period.accession_number for item in result.answer.evidence)
