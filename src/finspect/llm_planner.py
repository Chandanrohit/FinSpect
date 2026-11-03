from __future__ import annotations

import json
import os
from typing import Any

import requests
from pydantic import ValidationError

from finspect.query_planner import QueryPlan


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:3b"


SYSTEM_PROMPT = """
You are the query-planning component of FinSpect, an evidence-grounded
financial research assistant.

Convert the user's financial question into exactly one structured query plan.

Rules:
1. Return only data matching the supplied JSON schema.
2. Never invent financial values, filing facts, citations, or retrieved evidence.
3. Identify the company, requested reporting period, metrics, operation,
   retrieval sources, and answer requirements.
4. Use a benchmark_id only when the question clearly matches that benchmark.
5. If an essential detail is ambiguous, set needs_clarification=true and
   provide a concise clarification_question.
6. Use narrative sources for risks, legal proceedings, and qualitative
   disclosures; use XBRL or financial tables for numerical financial facts.
7. The plan describes what to retrieve and calculate. Do not calculate
   the final financial answer.
8. Preserve the user's original question exactly.
9. Choose "absolute_change" when the user asks how much a financial
   metric increased or decreased in currency or absolute units.
10. Choose "growth_rate" when the user explicitly asks for percentage
    growth or percentage change.
11. For absolute_change, set answer.expected_output to "currency".
12. Never substitute a percentage-growth calculation for an
    absolute-change request.
13. For comparisons between fiscal years, specify both the current
    and comparison periods and retrieve the same financial metric
    for both periods.
14. For Q12 equity-change questions, require one explicit annual fiscal
    year, use operation "equity_component_contribution", request both
    "shareholders_equity" and "equity_components" from "financial_table",
    and do not request a comparison period.
15. If an equity-change question has no explicit fiscal year, request
    clarification instead of guessing which annual filing to use.
16. For Q14 cash-allocation questions, require one explicit annual fiscal
    year and use operation "cash_allocation" with operating cash flow,
    share repurchases, dividends paid, and capital expenditure from the
    same 10-K period. Do not request a comparison period.
17. Treat share repurchases, cash dividends, and capital expenditure as
    cash outflow magnitudes in the calculation; keep operating cash flow
    as reported and request clarification if the fiscal year is missing.
18. For Q06 equity roll-forward questions, require one explicit annual
    fiscal year and use operation "balance_change" with shareholders' equity
    and equity components. Do not mark it as a year-over-year comparison;
    the pipeline resolves the prior fiscal year-end as the opening balance.
19. For Q16 regulatory, trade, sanctions, export-control, or government-policy
    risks, require one explicit annual fiscal year and use operation
    "regulatory_risk_analysis" with the single text metric "regulatory_risks"
    from "risk_factors". Do not request a numeric calculation or comparison.
20. For Q15 commitment/liquidity questions, require one explicit annual fiscal
    year and use operation "commitment_liquidity". Request future commitments,
    near-term commitments, cash and cash equivalents, and short-term investments
    or marketable securities for the same 10-K. Do not request a comparison.
    The pipeline will use the issuer's next-fiscal-year commitment bucket and
    must report unsupported when the schedule or units are ambiguous.
21. For Q02 segment-revenue contribution questions, require an explicit current
    and prior annual fiscal year, use operation "growth_contribution", and
    request total revenue plus reportable-segment revenue from one comparable
    segment disclosure. Do not mix product, geographic, or operating-segment
    classifications unless the filing identifies them as reportable segments.
22. For Q04 operating-expense contribution questions, require an explicit
    current and prior annual fiscal year and use operation
    "expense_growth_contribution". Request operating-expense categories and
    their reconciled total from the same 10-K; preserve issuer category labels
    and do not treat unlike categories as comparable across companies.
23. For Q17 geographic exposure questions, require one explicit annual fiscal
    year and use operation "geographic_exposure" with geographic revenue from
    the exact 10-K. Preserve the issuer's geographic labels and classification
    basis and include any stated limitation; do not substitute assets or
    reportable business segments for geographic revenue.
24. For Q18 market-risk sensitivity questions, require one explicit annual
    fiscal year and use operation "sensitivity_analysis" with a market-risk
    sensitivity and investment-portfolio balance from the exact 10-K. Use a
    clearly disclosed interest-rate investment-portfolio fair-value scenario
    only when its period-end balance and units can be matched; otherwise the
    pipeline must report unsupported. Do not treat a hypothetical scenario as
    a forecast or realized loss.
25. For Q19 legal-proceeding and contingency questions, require one explicit
    annual fiscal year and use operation "litigation_analysis" with legal
    proceedings and contingencies from the exact 10-K. Preserve cited filing
    excerpts and the company's own uncertainty language. Keep assessed fines,
    accrued liabilities, possible additional losses, and unquantified claims
    separate; do not infer a settlement value or legal outcome.
26. For Q20 material-disclosure synthesis, require one explicit annual fiscal
    year, use operation "material_disclosure_synthesis" with task_type
    "multi_part_analysis", and request "material_disclosures" from narrative
    sections of that exact 10-K. Preserve verbatim excerpts and visible amounts.
    Summarize co-disclosed evidence without claiming that a risk caused a
    reported result; do not invent quantitative exposure or imply completeness.
"""


class QueryPlanningError(RuntimeError):
    """Raised when the LLM cannot produce a valid query plan."""


class OllamaQueryPlanner:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_OLLAMA_URL,
        timeout: float = 180.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def plan(self, question: str) -> QueryPlan:
        question = question.strip()
        if not question:
            raise ValueError("Question must not be empty.")

        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "4m"),
            "think": False,
            "format": QueryPlan.model_json_schema(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "options": {"temperature": 0},
            "num_ctx": 4096,
            "num_predict": 1024,
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            raise QueryPlanningError(
                f"Could not reach Ollama at {self.base_url}: {exc}"
            ) from exc
        except ValueError as exc:
            raise QueryPlanningError(
                "Ollama returned an invalid HTTP response."
            ) from exc


        try:
            content = result["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise QueryPlanningError(
                "Ollama response is missing message.content."
            ) from exc

        try:
            data = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise QueryPlanningError(
                f"Ollama returned invalid JSON: {exc}"
            ) from exc

        try:
            return QueryPlan.model_validate(data)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: "
                f"{error['msg']}"
                for error in exc.errors()
            )
            raise QueryPlanningError(
                f"Ollama output failed QueryPlan validation: {details}"
            ) from exc


def planner_from_environment() -> OllamaQueryPlanner:
    """Create a planner using optional environment-variable overrides."""
    return OllamaQueryPlanner(
        model=os.getenv("FINSPECT_OLLAMA_MODEL", DEFAULT_MODEL),
        base_url=os.getenv(
            "FINSPECT_OLLAMA_URL", DEFAULT_OLLAMA_URL
        ),
    )
