
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

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
    """Build the SEC Archives directory URL from real SEC identifiers."""
    normalized_cik = str(cik).strip().lstrip("0")
    accession = str(accession_number).strip()

    if not normalized_cik.isdigit():
        raise ValueError("SEC CIK must contain digits.")

    accession_path = accession.replace("-", "")
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
    """Validate one raw SEC XBRL record and convert it to a typed fact."""

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
        key for key in required
        if raw.get(key) is None or raw.get(key) == ""
    ]
    if missing:
        raise ValueError(
            "SEC fact is missing required fields: " + ", ".join(missing)
        )
    try:
        value = Decimal(str(raw["value"]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("SEC fact value must be a valid decimal.") from exc

    if not value.is_finite():
        raise ValueError("SEC fact value must be finite.")

    try:
        end = date.fromisoformat(str(raw["end_date"]))
        filing_date = date.fromisoformat(str(raw["filing_date"]))
        start_text = raw.get("start_date")
        start = (
            date.fromisoformat(str(start_text))
            if start_text
            else None
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("SEC fact contains an invalid date.") from exc


    if not value.is_finite():
        raise ValueError("SEC fact value must be finite.")

    if filing_date < end:
        raise ValueError(
            "SEC filing date cannot precede the reporting period end."
        )

    if start is None:
        kind = PeriodKind.INSTANT
        basis = PeriodBasis.POINT_IN_TIME
    else:
        if start > end:
            raise ValueError(
                "SEC fact start date cannot be after end date."
            )
        kind = PeriodKind.DURATION
        duration_days = (end - start).days
        basis = (
            PeriodBasis.FULL_YEAR
            if 300 <= duration_days <= 400
            else PeriodBasis.CUSTOM
        )

    raw_unit = str(raw["unit"]).strip()
    if raw_unit != "USD":
        raise ValueError(
            f"Unsupported unit {raw_unit!r}; add an explicit unit mapping."
        )

    cik = str(raw["cik"]).strip().lstrip("0")
    accession = str(raw["accession_number"]).strip()
    taxonomy = str(raw["taxonomy"]).strip()
    concept = str(raw["concept"]).strip()

    if not cik.isdigit():
        raise ValueError("SEC CIK must contain digits.")
    if not taxonomy or not concept:
        raise ValueError("SEC taxonomy and concept must not be empty.")

    evidence = EvidenceRef(
        evidence_id=f"sec-xbrl:{accession}:{taxonomy}:{concept}:{end}",
        document_id=f"sec-filing:{accession}",
        evidence_type="xbrl_fact",
        source_url=sec_filing_url(cik, accession),
        accession_number=accession,
        taxonomy=taxonomy,
        concept=concept,
        context_start_date=start,
        context_end_date=end,
        filing_date=filing_date,
    )

    fiscal_year = raw.get("fiscal_year")
    if fiscal_year is not None:
        try:
            fiscal_year = int(fiscal_year)
        except (TypeError, ValueError) as exc:
            raise ValueError("fiscal_year must be an integer.") from exc

    period = ReportingPeriod(
        label=(
            f"FY{fiscal_year}"
            if fiscal_year is not None
            else f"{start or 'instant'} to {end}"
        ),
        kind=kind,
        basis=basis,
        role=period_role,
        start_date=start,
        end_date=end,
        fiscal_year=fiscal_year,
    )

    return FinancialFact(
        fact_id=f"sec:{accession}:{taxonomy}:{concept}:{end}",
        concept=concept,
        value=value,
        unit=Unit(
            kind=UnitKind.CURRENCY,
            currency=Currency.USD,
            scale=Decimal("1"),
            label="USD",
        ),
        period=period,
        entity=str(raw["company"]),
        scope=reporting_scope,
        source_label=str(raw.get("label") or concept),
        evidence=[evidence],
    )
