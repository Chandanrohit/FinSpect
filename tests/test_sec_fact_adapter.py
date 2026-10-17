
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finspect.edgar.fact_adapter import sec_fact_to_financial_fact
from finspect.schema import (
    PeriodKind,
    PeriodRole,
    ReportingScope,
)


@pytest.fixture
def raw_sec_fact():
    return {
        "cik": "1045810",
        "company": "NVIDIA CORP",
        "taxonomy": "us-gaap",
        "concept": "Revenues",
        "label": "Revenue from contracts with customers",
        "value": 130497000000,
        "unit": "USD",
        "start_date": "2024-01-29",
        "end_date": "2025-01-26",
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "form": "10-K",
        "filing_date": "2025-02-26",
        "accession_number": "0001045810-25-000023",
    }


def test_sec_fact_converts_to_canonical_fact(raw_sec_fact):
    fact = sec_fact_to_financial_fact(
        raw_sec_fact,
        period_role=PeriodRole.CURRENT,
    )

    assert fact.value == Decimal("130497000000")
    assert fact.unit.label == "USD"
    assert fact.unit.scale == Decimal("1")
    assert fact.period.kind == PeriodKind.DURATION
    assert fact.period.role == PeriodRole.CURRENT
    assert fact.period.start_date == date(2024, 1, 29)
    assert fact.period.end_date == date(2025, 1, 26)
    assert fact.concept == "Revenues"
    assert fact.scope == ReportingScope.CONSOLIDATED


def test_sec_fact_preserves_structured_provenance(raw_sec_fact):
    fact = sec_fact_to_financial_fact(
        raw_sec_fact,
        period_role=PeriodRole.CURRENT,
    )

    evidence = fact.evidence[0]

    assert evidence.evidence_type == "xbrl_fact"
    assert evidence.quote is None
    assert evidence.accession_number == "0001045810-25-000023"
    assert evidence.taxonomy == "us-gaap"
    assert evidence.concept == "Revenues"
    assert evidence.filing_date == date(2025, 2, 26)
    assert evidence.source_url == (
        "https://www.sec.gov/Archives/edgar/data/"
        "1045810/000104581025000023/"
    )


def test_adapter_rejects_missing_accession_number(raw_sec_fact):
    raw_sec_fact["accession_number"] = None

    with pytest.raises(ValueError, match="accession_number"):
        sec_fact_to_financial_fact(
            raw_sec_fact,
            period_role=PeriodRole.CURRENT,
        )


def test_adapter_rejects_non_numeric_value(raw_sec_fact):
    raw_sec_fact["value"] = "not-a-number"

    with pytest.raises(ValueError, match="valid decimal"):
        sec_fact_to_financial_fact(
            raw_sec_fact,
            period_role=PeriodRole.CURRENT,
        )


def test_adapter_rejects_unsupported_unit(raw_sec_fact):
    raw_sec_fact["unit"] = "shares"

    with pytest.raises(ValueError, match="Unsupported unit"):
        sec_fact_to_financial_fact(
            raw_sec_fact,
            period_role=PeriodRole.CURRENT,
        )


def test_evidence_rejects_missing_quote_and_structured_source():
    from finspect.schema import EvidenceRef

    with pytest.raises(ValidationError):
        EvidenceRef(
            evidence_id="evidence-1",
            document_id="document-1",
        )


def test_adapter_evidence_matches_fact_identity(raw_sec_fact):
    fact = sec_fact_to_financial_fact(
        raw_sec_fact,
        period_role=PeriodRole.CURRENT,
    )

    evidence = fact.evidence[0]

    assert evidence.accession_number == raw_sec_fact["accession_number"]
    assert evidence.taxonomy == raw_sec_fact["taxonomy"]
    assert evidence.concept == fact.concept
    assert evidence.context_end_date == fact.period.end_date
    assert evidence.context_start_date == fact.period.start_date


def test_adapter_rejects_invalid_reporting_dates(raw_sec_fact):
    raw_sec_fact["start_date"] = "2025-02-01"
    raw_sec_fact["end_date"] = "2025-01-26"

    with pytest.raises(ValueError, match="start date"):
        sec_fact_to_financial_fact(
            raw_sec_fact,
            period_role=PeriodRole.CURRENT,
        )

