
# src/finspect/period_resolver.py

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AnnualPeriod:
    fiscal_year: int
    start_date: str
    end_date: str
    form: str = "10-K"


def resolve_annual_period(cik: str, fiscal_year: int) -> AnnualPeriod:
    """
    Resolve an annual reporting period using SEC company facts.
    This implementation expects an existing EdgarClient with a
    get_company_facts(cik) method. Adjust that call if your client
    exposes the method under a different name.
    """
    from finspect.edgar.client import EdgarClient

    client = EdgarClient()
    payload = client.get_company_facts(cik)

    facts = payload.get("facts", {})
    us_gaap = facts.get("us-gaap", {})

    candidates = []

    for concept in us_gaap.values():
        units = concept.get("units", {})

        for unit_entries in units.values():
            for item in unit_entries:
                if item.get("form") != "10-K":
                    continue

                if item.get("fy") != fiscal_year:
                    continue

                start = item.get("start")
                end = item.get("end")

                if start and end:
                    candidates.append((start, end))

    if not candidates:
        raise ValueError(
            f"No annual 10-K duration facts found for fiscal year "
            f"{fiscal_year} and CIK {cik}."
        )

    # Use the most common start/end pair across duration facts.
    from collections import Counter

    period, _ = Counter(candidates).most_common(1)[0]
    start_date, end_date = period

    return AnnualPeriod(
        fiscal_year=fiscal_year,
        start_date=start_date,
        end_date=end_date,
    )
