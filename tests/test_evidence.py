
# tests/test_evidence.py

from datetime import date

import pytest
from pydantic import ValidationError

from finspect.evidence import (
    EvidenceRecord,
    evidence_from_fact,
    evidence_from_passage,
)


def test_cik_is_normalized():
    evidence = EvidenceRecord(
        evidence_id="E1",
        kind="financial_fact",
        cik="1045810",
    )

    assert evidence.cik == "0001045810"


def test_invalid_cik_is_rejected():
    with pytest.raises(ValidationError):
        EvidenceRecord(
            evidence_id="E1",
            kind="financial_fact",
            cik="NVDA",
        )


def test_sec_accession_url_is_derived():
    evidence = EvidenceRecord(
        evidence_id="E1",
        kind="financial_fact",
        cik="1045810",
        accession_number="0001045810-26-000021",
    )

    assert evidence.source_url == (
        "https://www.sec.gov/Archives/edgar/data/"
        "1045810/000104581026000021/"
    )


def test_fact_adapter_preserves_period_and_value():
    fact = {
        "label": "Revenue",
        "value": 1000,
        "unit": "USD",
        "start": "2024-01-29",
        "end": "2025-01-26",
        "fiscal_year": 2025,
        "form": "10-K",
        "filing_date": "2025-02-26",
        "accession_number": "0001045810-25-000023",
    }

    evidence = evidence_from_fact(
        fact,
        evidence_id="E2",
        cik="1045810",
        company_name="NVIDIA Corporation",
        ticker="NVDA",
    )

    assert evidence.kind == "financial_fact"
    assert evidence.metric == "Revenue"
    assert evidence.value == "1000"
    assert evidence.unit == "USD"
    assert evidence.period_end == date(2025, 1, 26)
    assert evidence.filing_date == date(2025, 2, 26)
    assert evidence.form == "10-K"


def test_narrative_passage_preserves_section_and_text():
    evidence = evidence_from_passage(
        evidence_id="E3",
        cik="1045810",
        text="The company disclosed regulatory risks.",
        section="Item 1A - Risk Factors",
        form="10-K",
        accession_number="0001045810-26-000021",
        relevance_score=0.9,
    )

    assert evidence.kind == "narrative_passage"
    assert evidence.section == "Item 1A - Risk Factors"
    assert "regulatory risks" in evidence.text
    assert evidence.relevance_score == 0.9
    assert evidence.source_url is not None


def test_citation_contains_provenance():
    evidence = EvidenceRecord(
        evidence_id="E4",
        kind="financial_fact",
        cik="1045810",
        metric="Revenue",
        period_end=date(2025, 1, 26),
        form="10-K",
        filing_date=date(2025, 2, 26),
        accession_number="0001045810-25-000023",
    )

    citation = evidence.to_citation()

    assert citation["evidence_id"] == "E4"
    assert citation["period_end"] == "2025-01-26"
    assert citation["form"] == "10-K"
    assert citation["url"] == evidence.source_url


def test_invalid_relevance_score_is_rejected():
    with pytest.raises(ValidationError):
        EvidenceRecord(
            evidence_id="E5",
            kind="narrative_passage",
            cik="1045810",
            relevance_score=1.5,
        )


def test_invalid_accession_does_not_create_url():
    evidence = EvidenceRecord(
        evidence_id="E6",
        kind="financial_fact",
        cik="1045810",
        accession_number="not-an-accession",
    )

    assert evidence.source_url is None
