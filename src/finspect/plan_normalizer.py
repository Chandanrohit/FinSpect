from __future__ import annotations

import re

from finspect.query_planner import QueryPlan


# Known companies are resolved deterministically, not trusted to the LLM.
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

    # A year attached to a filing/annual-report request is a fiscal-year hint,
    # even when the user says "10-K in 2025" instead of "FY2025".
    if re.search(r"\b(?:10\s*-?\s*K|annual\s+report)\b", question, re.IGNORECASE):
        for match in re.finditer(r"(?<![A-Za-z0-9])((?:19|20|21)\d{2})(?!\d)", question):
            found.add(int(match.group(1)))

    return sorted(found)


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
    question = plan_data["original_question"]
    has_quarter = bool(
        re.search(
            r"\bQ[1-4](?:\s*(?:FY|fiscal\s+year)?\s*\d{4})?\b|"
            r"\b(?:first|second|third|fourth)\s+(?:fiscal\s+)?quarter\b",
            question,
            re.IGNORECASE,
        )
    )
    if not has_quarter and period["period_kind"] == "unspecified":
        period["period_kind"] = "annual"

    if len(years) >= 2:
        if not has_quarter:
            period["period_kind"] = "annual"
        period["comparison_required"] = True
        period["comparison_period"] = f"FY{years[-2]}"


def _normalize_supported_benchmark_intent(plan_data: dict) -> None:
    """Repair common Qwen intent-label errors from explicit question wording."""
    question = plan_data["original_question"]
    question_lower = question.casefold()
    years = _explicit_fiscal_years(question)
    plan_data["metrics"] = list(plan_data["metrics"])
    period = plan_data["period"]

    if (
        re.search(r"\boperating\s+margin\b", question_lower)
        and len(years) >= 2
    ):
        # Qwen often labels this as change_relationship and emits one metric
        # named "margin_change". The calculation requires operating income / revenue.
        plan_data["benchmark_id"] = "Q03"
        plan_data["task_type"] = "comparison"
        plan_data["operation"] = "margin_change"
        plan_data["metrics"] = [
            {
                "name": "total revenue",
                "role": "denominator",
                "sources": ["xbrl"],
                "required": True,
                "concept_hint": "Revenues",
            },
            {
                "name": "operating income",
                "role": "primary",
                "sources": ["xbrl"],
                "required": True,
                "concept_hint": "OperatingIncomeLoss",
            },
        ]
        plan_data["retrieval"]["sources"] = ["xbrl"]
        plan_data["answer"]["expected_output"] = "percentage_points"
        plan_data["needs_clarification"] = False
        plan_data["clarification_question"] = None

    is_risk_question = bool(
        re.search(r"\b(?:risk|risks|regulatory|trade|export)\b", question_lower)
    )
    if plan_data.get("benchmark_id") == "Q16" and is_risk_question and years:
        # A filing-risk prompt needs an annual filing and risk-factor evidence.
        # Do not let a malformed planner label turn it into a comparison or
        # a numeric geographic-revenue operation.
        plan_data["task_type"] = "disclosure_analysis"
        plan_data["operation"] = "regulatory_risk_analysis"
        plan_data["metrics"] = [
            {
                "name": "risk factors",
                "role": "primary",
                "sources": ["risk_factors"],
                "required": True,
                "concept_hint": None,
            }
        ]
        plan_data["retrieval"]["sources"] = ["risk_factors"]
        period["period_kind"] = "annual"
        period["fiscal_year"] = years[-1]
        period["period_label"] = f"FY{years[-1]}"
        period["comparison_required"] = False
        period["comparison_period"] = None
        plan_data["answer"]["expected_output"] = "text"
        plan_data["needs_clarification"] = False
        plan_data["clarification_question"] = None


def normalize_query_plan(plan: QueryPlan) -> QueryPlan:
    """
    Apply deterministic corrections after LLM output validation.

    This does not invent missing financial facts or decide whether a
    calculation is supported by retrieved evidence.
    """
    data = plan.model_dump(mode="json")

    _deduplicate_sources(data)
    _normalize_explicit_years(data)
    _normalize_supported_benchmark_intent(data)

    # Revalidate after deterministic changes.
    return QueryPlan.model_validate(data)
