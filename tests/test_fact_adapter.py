
from datetime import date
from decimal import Decimal

import pytest

from finspect.edgar.fact_adapter import (
    sec_fact_to_financial_fact,
    sec_filing_url,
)
from finspect.schema import (
    PeriodBasis,
    PeriodKind,
    PeriodRole,
)


@pytest.fixture
def raw_fact():
    return {
        "cik": "0001045810",
        "company": "NVIDIA Corporation",
        "taxonomy": "us-gaap",
        "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "label": "Revenue",
        "value": "1000000",
        "unit": "USD",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "fiscal_year": 2024,
        "form": "10-K",
        "filing_date": "2025-02-20",
        "accession_number": "0001045810-25-000010",
    }


def test_converts_annual_sec_fact(raw_fact):
    fact = sec_fact_to_financial_fact(
        raw_fact,
        period_role=PeriodRole.CURRENT,
    )

    assert fact.value == Decimal("1000000")
    assert fact.unit.label == "USD"
    assert fact.period.kind == PeriodKind.DURATION
    assert fact.period.basis == PeriodBasis.FULL_YEAR
    assert fact.period.start_date == date(2024, 1, 1)
    assert fact.period.end_date == date(2024, 12, 31)
    assert fact.evidence[0].evidence_type == "xbrl_fact"
    assert fact.evidence[0].concept == raw_fact["concept"]
    assert fact.evidence[0].source_url.startswith(
        "https://www.sec.gov/Archives/edgar/data/"
    )


def test_converts_instant_fact_without_duration_bug(raw_fact):
    raw_fact["start_date"] = None
    raw_fact["end_date"] = "2024-12-31"

    fact = sec_fact_to_financial_fact(
        raw_fact,
        period_role=PeriodRole.CURRENT,
    )

    assert fact.period.kind == PeriodKind.INSTANT
    assert fact.period.basis == PeriodBasis.POINT_IN_TIME
    assert fact.period.start_date is None


def test_rejects_non_finite_value(raw_fact):
    raw_fact["value"] = "NaN"

    with pytest.raises(ValueError, match="finite"):
        sec_fact_to_financial_fact(
            raw_fact,
            period_role=PeriodRole.CURRENT,
        )


def test_rejects_unsupported_unit(raw_fact):
    raw_fact["unit"] = "shares"

    with pytest.raises(ValueError, match="Unsupported unit"):
        sec_fact_to_financial_fact(
            raw_fact,
            period_role=PeriodRole.CURRENT,
        )


def test_rejects_start_after_end(raw_fact):
    raw_fact["start_date"] = "2025-01-01"
    raw_fact["end_date"] = "2024-12-31"

    with pytest.raises(ValueError, match="start date"):
        sec_fact_to_financial_fact(
            raw_fact,
            period_role=PeriodRole.CURRENT,
        )


def test_rejects_missing_required_metadata(raw_fact):
    del raw_fact["accession_number"]

    with pytest.raises(ValueError, match="accession_number"):
        sec_fact_to_financial_fact(
            raw_fact,
            period_role=PeriodRole.CURRENT,
        )


def test_builds_sec_filing_url():
    url = sec_filing_url(
        "0001045810",
        "0001045810-25-000010",
    )

    assert url == (
        "https://www.sec.gov/Archives/edgar/data/"
        "1045810/000104581025000010/"
    )
