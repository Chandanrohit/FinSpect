from __future__ import annotations

import re

from finspect.query_planner import QueryPlan


# Known companies are resolved deterministically, not trusted to the LLM.
COMPANY_REGISTRY = {
    "NVDA": {
        "name": "NVIDIA Corporation",
        "cik": "0001045810",
        "aliases": ("nvidia", "nvidia corporation"),
    },
}


def _explicit_fiscal_years(question: str) -> list[int]:
    """Extract explicit FY2024 / fiscal year 2025 references."""
    patterns = (
        r"\bFY\s?((?:19|20|21)\d{2})\b",
        r"\bfiscal\s+year\s+((?:19|20|21)\d{2})\b",
    )
    found: set[int] = set()

    for pattern in patterns:
        for match in re.finditer(pattern, question, flags=re.IGNORECASE):
            found.add(int(match.group(1)))

    return sorted(found)


def _resolve_known_company(plan_data: dict) -> None:
    """Canonicalize a company when its ticker/name matches our registry."""
    company = plan_data["company"]
    ticker = (company.get("ticker") or "").strip().upper()
    name = (company.get("name") or "").strip().casefold()

    match = COMPANY_REGISTRY.get(ticker)

    if match is None:
        for known_ticker, entry in COMPANY_REGISTRY.items():
            if name in entry["aliases"] or name == entry["name"].casefold():
                match = entry
                ticker = known_ticker
                break

    if match is not None:
        company["name"] = match["name"]
        company["ticker"] = ticker
        company["cik"] = match["cik"]


def _deduplicate_sources(plan_data: dict) -> None:
    """Keep retrieval source lists unique while preserving their order."""
    retrieval = plan_data["retrieval"]
    retrieval["sources"] = list(dict.fromkeys(retrieval["sources"]))

    for metric in plan_data["metrics"]:
        metric["sources"] = list(dict.fromkeys(metric["sources"]))


def _normalize_explicit_years(plan_data: dict) -> None:
    """Put explicit fiscal years into typed period fields."""
    years = _explicit_fiscal_years(plan_data["original_question"])
    if not years:
        return

    period = plan_data["period"]

    # Use the latest explicitly requested fiscal year as the primary year.
    period["fiscal_year"] = years[-1]
    period["period_label"] = f"FY{years[-1]}"

    if len(years) >= 2:
        period["comparison_required"] = True
        period["comparison_period"] = f"FY{years[-2]}"


def normalize_query_plan(plan: QueryPlan) -> QueryPlan:
    """
    Apply deterministic corrections after LLM output validation.

    This does not invent missing financial facts or decide whether a
    calculation is supported by retrieved evidence.
    """
    data = plan.model_dump(mode="json")

    _resolve_known_company(data)
    _deduplicate_sources(data)
    _normalize_explicit_years(data)

    # Revalidate after deterministic changes.
    return QueryPlan.model_validate(data)
