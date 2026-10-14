
# src/finspect/evidence.py

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from urllib.parse import quote

from pydantic import Field, field_validator

from finspect.schema import FSModel


EvidenceKind = Literal["financial_fact", "narrative_passage"]


class EvidenceRecord(FSModel):
    """A standardized, traceable piece of SEC filing evidence."""

    evidence_id: str = Field(min_length=1)
    kind: EvidenceKind

    company_name: str | None = None
    cik: str = Field(min_length=1)
    ticker: str | None = None

    # Financial fact fields
    metric: str | None = None
    value: str | None = None
    unit: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    fiscal_year: int | None = None

    # Filing provenance
    form: str | None = None
    filing_date: date | None = None
    accession_number: str | None = None
    filing_url: str | None = None

    # Narrative evidence fields
    text: str | None = None
    section: str | None = None

    # Useful for debugging and retrieval evaluation
    retrieval_method: str | None = None
    relevance_score: float | None = Field(default=None, ge=0, le=1)

    @field_validator("cik")
    @classmethod
    def normalize_cik(cls, value: str) -> str:
        value = value.strip()
        if not value.isdigit():
            raise ValueError("CIK must contain digits only")
        return value.zfill(10)

    @field_validator("accession_number")
    @classmethod
    def normalize_accession(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return None
        # SEC accession numbers normally contain hyphens.
        cleaned = value.strip()
        return cleaned or None

    @field_validator("value", "text", "metric", "unit", "section")
    @classmethod
    def strip_optional_strings(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @property
    def source_url(self) -> str | None:
        """Return the filing URL, deriving the SEC accession URL if possible."""
        if self.filing_url:
            return self.filing_url

        if not self.accession_number:
            return None

        accession_compact = self.accession_number.replace("-", "")
        if not accession_compact.isdigit():
            return None

        return (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(self.cik)}/{accession_compact}/"
        )

    def to_citation(self) -> dict[str, Any]:
        """Return compact citation metadata for the answer builder."""
        return {
            "evidence_id": self.evidence_id,
            "company": self.company_name or self.ticker or self.cik,
            "metric": self.metric,
            "section": self.section,
            "period_start": (
                self.period_start.isoformat()
                if self.period_start else None
            ),
            "period_end": (
                self.period_end.isoformat()
                if self.period_end else None
            ),
            "form": self.form,
            "filing_date": (
                self.filing_date.isoformat()
                if self.filing_date else None
            ),
            "accession_number": self.accession_number,
            "url": self.source_url,
        }


def evidence_from_fact(
    fact: dict[str, Any],
    *,
    evidence_id: str,
    cik: str,
    company_name: str | None = None,
    ticker: str | None = None,
) -> EvidenceRecord:
    """Adapt the existing FinancialFactRetriever dictionary into evidence."""

    return EvidenceRecord(
        evidence_id=evidence_id,
        kind="financial_fact",
        company_name=company_name,
        cik=cik,
        ticker=ticker,
        metric=fact.get("label") or fact.get("concept"),
        value=(
            str(fact["value"])
            if fact.get("value") is not None
            else None
        ),
        unit=fact.get("unit"),
        period_start=fact.get("start"),
        period_end=fact.get("end"),
        fiscal_year=fact.get("fiscal_year"),
        form=fact.get("form"),
        filing_date=fact.get("filing_date"),
        accession_number=fact.get("accession_number"),
        filing_url=fact.get("filing_url"),
        retrieval_method="sec_companyfacts",
    )


def evidence_from_passage(
    *,
    evidence_id: str,
    cik: str,
    text: str,
    section: str,
    form: str | None = None,
    filing_date: date | None = None,
    accession_number: str | None = None,
    filing_url: str | None = None,
    company_name: str | None = None,
    ticker: str | None = None,
    relevance_score: float | None = None,
) -> EvidenceRecord:
    """Create evidence from a passage extracted from an SEC filing."""

    return EvidenceRecord(
        evidence_id=evidence_id,
        kind="narrative_passage",
        company_name=company_name,
        cik=cik,
        ticker=ticker,
        text=text,
        section=section,
        form=form,
        filing_date=filing_date,
        accession_number=accession_number,
        filing_url=filing_url,
        retrieval_method="filing_passage",
        relevance_score=relevance_score,
    )
