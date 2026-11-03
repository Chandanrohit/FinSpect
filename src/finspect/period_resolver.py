
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import date

from finspect.edgar.xbrl import XBRLService


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
    Find the current annual revenue fact for the requested filing year.

    SEC ``fy``/``fp`` metadata identifies the annual filing even when the
    period ends in the following calendar year. Comparative facts repeated
    in that filing share its accession number, so select the latest annual
    period from the earliest matching 10-K.
    """
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for concept_name in REVENUE_CONCEPTS:
        concept = us_gaap.get(concept_name, {})
        current_filing_facts = []
        fallback_facts = []

        for unit, entries in concept.get("units", {}).items():
            if not re.fullmatch(r"[A-Z]{3}", unit):
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

                reported_fy = fact.get("fy")
                if reported_fy is not None:
                    try:
                        matches_fy = int(reported_fy) == fiscal_year
                    except (TypeError, ValueError):
                        matches_fy = False
                    if matches_fy and fact.get("fp") in (None, "FY"):
                        current_filing_facts.append({
                            **fact,
                            "concept": concept_name,
                            "unit": unit,
                            "duration_days": duration_days,
                        })
                elif end_date.year == fiscal_year:
                    fallback_facts.append({
                        **fact,
                        "concept": concept_name,
                        "unit": unit,
                        "duration_days": duration_days,
                    })

        candidates = current_filing_facts or fallback_facts
        if candidates:
            # Prefer USD when an issuer reports it; otherwise require exactly
            # one reported currency and keep all later inputs in that unit.
            usd_candidates = [item for item in candidates if item["unit"] == "USD"]
            if usd_candidates:
                candidates = usd_candidates
            elif len({item["unit"] for item in candidates}) > 1:
                raise ValueError(
                    f"Multiple revenue currencies are available for FY{fiscal_year}."
                )
            candidates.sort(
                key=lambda item: (
                    item.get("filed", "9999-12-31"),
                    item.get("accn", ""),
                )
            )
            earliest_filing_date = candidates[0].get("filed", "9999-12-31")
            filing_candidates = [
                item for item in candidates
                if item.get("filed", "9999-12-31") == earliest_filing_date
            ]
            latest_end = max(item["end"] for item in filing_candidates)
            selected_candidates = [
                item for item in filing_candidates if item["end"] == latest_end
            ]
            if len({str(item.get("val")) for item in selected_candidates}) > 1:
                raise ValueError(
                    "Conflicting annual revenue values were reported "
                    "for the same SEC filing and period."
                )
            return selected_candidates[0]

    raise ValueError(
        f"No annual revenue fact found for FY{fiscal_year}. "
        "Check the available revenue concepts and reporting dates."
    )


@dataclass(frozen=True)
class AnnualPeriod:
    """Verified dates for one annual SEC reporting period."""

    fiscal_year: int
    start_date: str
    end_date: str
    form: str = "10-K"
    concept: str = ""
    filing_date: str | None = None
    accession_number: str | None = None
    currency: str = "USD"
    resolved_revenue_value: Decimal | None = None
    revenue_derivation_inputs: tuple[dict, ...] = ()


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
        concept=fact.get("concept", "Revenues"),
        filing_date=fact.get("filed"),
        accession_number=fact.get("accn") or fact.get("accession_number"),
        currency=fact["unit"],
    )


def _select_original_quarter_fact(
    entries: list[dict], *, fiscal_year: int, quarter: int, concept_name: str,
    duration_days: tuple[int, int],
) -> dict | None:
    """Select one unambiguous fact from the original 10-Q for an SEC fiscal quarter."""
    candidates = []
    for fact in entries:
        if fact.get("form") != "10-Q" or fact.get("fp") != f"Q{quarter}":
            continue
        try:
            if int(fact.get("fy")) != fiscal_year:
                continue
            days = (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days
        except (KeyError, TypeError, ValueError):
            continue
        if duration_days[0] <= days <= duration_days[1] and fact.get("filed") and fact.get("accn"):
            candidates.append({**fact, "concept": concept_name, "unit": "USD"})
    if not candidates:
        return None
    first_filed = min(item["filed"] for item in candidates)
    original_filing = [item for item in candidates if item["filed"] == first_filed]
    # A 10-Q can include the prior-year comparative context in the same filing.
    # Keep the latest period end from that original filing as the requested FY.
    latest_end = max(item["end"] for item in original_filing)
    original_filing = [item for item in original_filing if item["end"] == latest_end]
    identities = {(item["accn"], item["start"], item["end"]) for item in original_filing}
    if len(identities) != 1 or len({str(item["val"]) for item in original_filing}) != 1:
        raise ValueError(f"Conflicting Q{quarter} revenue facts for FY{fiscal_year}.")
    return original_filing[0]


def find_quarterly_revenue_fact(company_facts: dict, fiscal_year: int, quarter: int) -> dict:
    """Resolve original standalone Q1-Q3 revenue, deriving Q2/Q3 from consecutive YTD facts if needed."""
    if quarter not in (1, 2, 3):
        raise ValueError("Quarter resolver currently supports fiscal quarters 1 through 3.")
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for concept_name in REVENUE_CONCEPTS:
        entries = us_gaap.get(concept_name, {}).get("units", {}).get("USD", [])
        direct = _select_original_quarter_fact(
            entries, fiscal_year=fiscal_year, quarter=quarter,
            concept_name=concept_name, duration_days=(70, 110),
        )
        if direct:
            return direct

        if quarter == 1:
            continue
        ytd_ranges = {2: (150, 210), 3: (220, 320)}
        current_ytd = _select_original_quarter_fact(
            entries, fiscal_year=fiscal_year, quarter=quarter,
            concept_name=concept_name, duration_days=ytd_ranges[quarter],
        )
        prior_quarter_ytd_days = (70, 110) if quarter == 2 else (150, 210)
        prior_ytd = _select_original_quarter_fact(
            entries, fiscal_year=fiscal_year, quarter=quarter - 1,
            concept_name=concept_name, duration_days=prior_quarter_ytd_days,
        )
        if not current_ytd or not prior_ytd:
            continue
        if (
            prior_ytd["start"] != current_ytd["start"]
            or prior_ytd["end"] >= current_ytd["end"]
            or prior_ytd["filed"] >= current_ytd["filed"]
        ):
            continue
        standalone_start = date.fromisoformat(prior_ytd["end"]).toordinal() + 1
        standalone_days = (
            date.fromisoformat(current_ytd["end"]).toordinal() - standalone_start
        )
        if not 70 <= standalone_days <= 110:
            continue
        try:
            standalone_value = Decimal(str(current_ytd["val"])) - Decimal(str(prior_ytd["val"]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("YTD revenue facts are not numeric and cannot be differenced.") from exc
        if not standalone_value.is_finite() or standalone_value < 0:
            raise ValueError("Derived standalone quarterly revenue is invalid.")
        return {
            **current_ytd,
            "start": date.fromordinal(standalone_start).isoformat(),
            "val": standalone_value,
            "derived_from_ytd": True,
            "derivation_inputs": (prior_ytd, current_ytd),
        }
    raise ValueError(f"No standalone or safely derivable Q{quarter} USD revenue fact found for FY{fiscal_year}.")


def resolve_quarterly_period(cik: str, fiscal_year: int, quarter: int, *, xbrl_service: XBRLService) -> AnnualPeriod:
    """Resolve a standalone Q1-Q3 period from the issuer's SEC fiscal metadata."""
    fact = find_quarterly_revenue_fact(xbrl_service.get_company_facts(cik), fiscal_year, quarter)
    return AnnualPeriod(
        fiscal_year=fiscal_year, start_date=fact["start"], end_date=fact["end"],
        form=fact["form"], concept=fact["concept"], filing_date=fact["filed"],
        accession_number=fact["accn"], currency=fact["unit"],
        resolved_revenue_value=Decimal(str(fact["val"])),
        revenue_derivation_inputs=tuple(fact.get("derivation_inputs", ())),
    )

