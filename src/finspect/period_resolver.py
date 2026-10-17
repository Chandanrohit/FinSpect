
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from finspect.edgar.xbrl import XBRLService


from datetime import date


REVENUE_CONCEPTS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
)


def find_annual_revenue_fact(
    company_facts: dict,
    fiscal_year: int,
) -> dict:
    """
    Find an annual revenue fact by its reporting dates.

    The requested fiscal year is inferred from the period end year.
    We do not rely on the SEC 'fy' field alone because comparative
    facts can carry metadata from a later filing.
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    candidates = []

    for concept_name in REVENUE_CONCEPTS:
        concept = us_gaap.get(concept_name, {})

        for unit, entries in concept.get("units", {}).items():
            if unit != "USD":
                continue

            for fact in entries:
                if fact.get("form") != "10-K":
                    continue

                start = fact.get("start")
                end = fact.get("end")

                # Revenue is a duration fact, not a point-in-time fact.
                if not start or not end:
                    continue

                start_date = date.fromisoformat(start)
                end_date = date.fromisoformat(end)
                duration_days = (end_date - start_date).days

                # Accept a normal annual reporting period.
                if not 300 <= duration_days <= 400:
                    continue

                # Match the requested reporting period by its end date.
                if end_date.year != fiscal_year:
                    continue

                candidates.append({
                    **fact,
                    "concept": concept_name,
                    "unit": unit,
                    "duration_days": duration_days,
                })

    if not candidates:
        raise ValueError(
            f"No annual revenue fact found for FY{fiscal_year}. "
            "Check the available revenue concepts and reporting dates."
        )

    # Prefer the earliest filing that reported this period, rather
    # than a later filing that repeats it as a comparative.
    candidates.sort(
        key=lambda fact: (
            fact["end"],
            fact.get("filed", "9999-12-31"),
        ),
        reverse=True,
    )

    earliest_period_end = candidates[0]["end"]
    same_period = [
        fact for fact in candidates
        if fact["end"] == earliest_period_end
    ]
    same_period.sort(key=lambda fact: fact.get("filed", "9999-12-31"))

    return same_period[0]


@dataclass(frozen=True)
class AnnualPeriod:
    """Verified dates for one annual SEC reporting period."""

    fiscal_year: int
    start_date: str
    end_date: str
    form: str = "10-K"
    concept: str = "Revenues"


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

    fact = find_annual_revenue_fact(company_facts=payload, fiscal_year=fiscal_year)
    return AnnualPeriod(
        fiscal_year=fiscal_year,
        start_date=fact["start"],
        end_date=fact["end"],
        form=fact.get("form", "10-K"),
        concept=fact.get("concept", "Revenues")
    )

