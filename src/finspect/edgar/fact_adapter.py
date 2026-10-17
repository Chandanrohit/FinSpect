
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from finspect.schema import (
    Currency,
    EvidenceRef,
    FinancialFact,
    PeriodBasis,
    PeriodKind,
    PeriodRole,
    ReportingPeriod,
    ReportingScope,
    Unit,
    UnitKind,
)


def sec_filing_url(cik: str | int, accession_number: str) -> str:
    """Build the SEC Archives directory URL for a real accession number."""
    normalized_cik = str(cik).lstrip("0")
    if not normalized_cik.isdigit():
        raise ValueError("SEC CIK must contain digits.")

    if not accession_number.strip():
        raise ValueError("SEC accession number cannot be empty.")

    accession_path = accession_number.replace("-", "")
    if not accession_path.isdigit():
        raise ValueError("Invalid SEC accession number.")

    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(normalized_cik)}/{accession_path}/"
    )


def sec_fact_to_financial_fact(
    raw: dict[str, Any],
    *,
    period_role: PeriodRole,
    reporting_scope: ReportingScope = ReportingScope.CONSOLIDATED,
) -> FinancialFact:
    """Validate and convert one raw SEC XBRL fact to FinSpect's schema."""

    required = (
        "cik",
        "company",
        "taxonomy",
        "concept",
        "value",
        "unit",
        "end_date",
        "form",
        "filing_date",
        "accession_number",
    )
    missing = [
        field for field in required
        if raw.get(field) is None or raw.get(field) == ""
    ]
    if missing:
        raise ValueError(
            f"SEC fact is missing required fields: {', '.join(missing)}"
        )

    try:
        value = Decimal(str(raw["value"]))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("SEC fact value must be a valid decimal.") from exc

    if not value.is_finite():
        raise ValueError("SEC fact value must be finite.")

    start = raw.get("start_date")
    end = date.fromisoformat(raw["end_date"])
    filing_date = date.fromisoformat(raw["filing_date"])
    start_date = date.fromisoformat(start) if start else None

    if start_date is None:
        period_kind = PeriodKind.INSTANT
        period_basis = PeriodBasis.POINT_IN_TIME
    else:
        period_kind = PeriodKind.DURATION
        # This adapter does not guess quarter vs full-year from dates.
        period_basis = PeriodBasis.CUSTOM

    if period_kind == PeriodKind.DURATION and start_date > end:
        raise ValueError("SEC fact start date cannot be after end date.")

    raw_unit = str(raw["unit"])
    if raw_unit == "USD":
        unit = Unit(
            kind=UnitKind.CURRENCY,
            currency=Currency.USD,
            scale=Decimal("1"),
            label="USD",
        )
    else:
        # Do not silently misclassify shares, percentages, or other units.
        raise ValueError(
            f"Unsupported unit {raw_unit!r}; add an explicit unit mapping."
        )

    cik = str(raw["cik"]).lstrip("0")
    accession = str(raw["accession_number"])
    taxonomy = str(raw["taxonomy"])
    concept = str(raw["concept"])
    source_url = sec_filing_url(cik, accession)

    # XBRL values are structured data; no quotation is fabricated.
    evidence = EvidenceRef(
        evidence_id=f"sec-xbrl:{accession}:{taxonomy}:{concept}:{end}",
        document_id=f"sec-filing:{accession}",
        evidence_type="xbrl_fact",
        source_url=source_url,
        accession_number=accession,
        taxonomy=taxonomy,
        concept=concept,
        context_start_date=start_date,
        context_end_date=end,
        filing_date=filing_date,
    )

    fiscal_year = raw.get("fiscal_year")
    if fiscal_year is not None:
        fiscal_year = int(fiscal_year)

    period = ReportingPeriod(
        label=(
            f"FY{fiscal_year}"
            if fiscal_year is not None
            else f"{start_date or 'instant'} to {end}"
        ),
        kind=period_kind,
        basis=period_basis,
        role=period_role,
        start_date=start_date,
        end_date=end,
        fiscal_year=fiscal_year,
    )

    return FinancialFact(
        fact_id=f"sec:{accession}:{taxonomy}:{concept}:{end}",
        concept=concept,
        value=value,
        unit=unit,
        period=period,
        entity=str(raw["company"]),
        scope=reporting_scope,
        source_label=str(raw.get("label") or concept),
        evidence=[evidence],
    )
