
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from finspect.edgar.xbrl import XBRLService


@dataclass(frozen=True)
class AnnualPeriod:
    """Verified dates for one annual SEC reporting period."""

    fiscal_year: int
    start_date: str
    end_date: str
    form: str = "10-K"


REVENUE_CONCEPT = (
    "RevenueFromContractWithCustomerExcludingAssessedTax"
)


def resolve_annual_period(
    cik: str,
    fiscal_year: int,
    *,
    xbrl_service: XBRLService,
) -> AnnualPeriod:
    """
    Resolve fiscal-year dates from the company's SEC XBRL facts.

    Uses annual revenue entries as the period anchor. It does not
    assume that a company's fiscal year ends on December 31.
    """
    payload = xbrl_service.get_company_facts(cik)

    us_gaap = payload.get("facts", {}).get("us-gaap", {})
    concept = us_gaap.get(REVENUE_CONCEPT)

    if concept is None:
        raise ValueError(
            f"SEC company facts do not contain {REVENUE_CONCEPT!r} "
            f"for CIK {cik}."
        )

    candidates: list[tuple[str, str, str]] = []

    for unit, entries in concept.get("units", {}).items():
        for item in entries:
            if item.get("form") != "10-K":
                continue

            if item.get("fy") != fiscal_year:
                continue

            if item.get("fp") != "FY":
                continue

            start = item.get("start")
            end = item.get("end")
            filed = item.get("filed", "")

            if not start or not end:
                continue

            try:
                start_day = date.fromisoformat(start)
                end_day = date.fromisoformat(end)
            except ValueError:
                continue

            duration_days = (end_day - start_day).days

            # An annual income-statement fact should span approximately
            # one year. Exclude quarter and year-to-date durations.
            if not 300 <= duration_days <= 400:
                continue

            candidates.append((filed, start, end))

    if not candidates:
        raise ValueError(
            f"No suitable annual revenue period found for FY{fiscal_year} "
            f"and CIK {cik}. Check the company's taxonomy and SEC facts."
        )

    # Prefer the most recently filed matching annual fact.
    candidates.sort(key=lambda item: item[0])
    _, start_date, end_date = candidates[-1]

    return AnnualPeriod(
        fiscal_year=fiscal_year,
        start_date=start_date,
        end_date=end_date,
        form="10-K",
    )
