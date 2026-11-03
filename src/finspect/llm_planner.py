from __future__ import annotations

import json
import os
from typing import Any

import requests
from pydantic import ValidationError

from finspect.query_planner import QueryPlan


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:3b"


SYSTEM_PROMPT = """You plan questions for FinSpect, an SEC filing research assistant.
Return one JSON object matching the supplied schema. Make a retrieval plan only;
never invent values, filings, or citations, and never calculate the final answer.
Preserve the question exactly. Identify company, period(s), metrics, operation,
sources, and output. Do not guess a missing company/year; ask one concise
clarifying question when an essential detail is missing. Set benchmark_id only
when the match is clear. Use XBRL/tables for numbers and filing sections for
narrative. Comparisons must use the same metric and compatible periods/units.
For absolute currency change use absolute_change and output currency; for
percentage growth use growth_rate. Never confuse the two.

Benchmark operation guide (use only the clearly matching rule):
Q01 revenue growth/change: growth_rate or absolute_change.
Q02 segment revenue contribution: growth_contribution; compare total and
reportable-segment revenue in both annual periods; preserve segment basis.
Q03 operating margin comparison: margin_change.
Q04 expense-category contribution: expense_growth_contribution; reconcile
expense categories to total and retain issuer labels.
Q05 net-income change relative to operating-income change: change_relationship.
Q06 equity roll-forward: balance_change; one FY, opening balance is prior
year-end; no YoY comparison flag.
Q07 change in liquid assets relative to change in total assets:
liquidity_asset_contribution.
Q08 receivables growth versus revenue growth: growth_comparison.
Q09 inventory turnover/trend: inventory_revenue_growth_comparison.
Q10 share repurchase/cash-flow comparison: capital_allocation_ratio.
Q11 share dilution: dilution_ratio.
Q12 largest equity component change: equity_component_contribution; one FY,
financial_table sources, request equity and components.
Q13 operating cash flow conversion: cash_conversion.
Q14 cash allocation: cash_allocation; one FY; request operating cash flow,
repurchases, dividends, and capex; outflows are magnitudes.
Q15 commitments/liquidity: commitment_liquidity; one FY; request commitments,
cash, and short-term investments; ambiguous schedule/units means unsupported.
Q16 regulatory/trade/export risks: regulatory_risk_analysis; one FY, narrative
from risk_factors, no numeric calculation.
Q17 geographic revenue: geographic_exposure; one FY, exact 10-K; retain labels
and classification basis; do not substitute assets or segments.
Q18 market-risk sensitivity: sensitivity_analysis; one FY, exact 10-K; match
scenario, balance, and units; never call a hypothetical loss a forecast.
Q19 legal proceedings/contingencies: litigation_analysis; one FY, exact 10-K;
preserve uncertainty and keep fines, accruals, possible losses, and claims apart.
Q20 material disclosures: material_disclosure_synthesis, multi_part_analysis;
one FY, exact filing excerpts; do not assert causation or completeness.

For YoY Q1-Q3 revenue, use quarterly periods and matching standalone 10-Q
quarters from consecutive fiscal years. Never treat YTD as a quarter. Q4 and
quarter-to-quarter comparisons are unsupported unless verified by the pipeline.
"""


class QueryPlanningError(RuntimeError):
    """Raised when the LLM cannot produce a valid query plan."""


class OllamaQueryPlanner:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_OLLAMA_URL,
        timeout: float | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = (
            float(os.getenv("FINSPECT_OLLAMA_TIMEOUT", "300"))
            if timeout is None
            else timeout
        )

    def plan(self, question: str) -> QueryPlan:
        question = question.strip()
        if not question:
            raise ValueError("Question must not be empty.")

        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "4m"),
            "think": False,
            "format": compact_json_schema(QueryPlan.model_json_schema()),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "options": {"temperature": 0},
            "num_ctx": int(os.getenv("FINSPECT_OLLAMA_NUM_CTX", "4096")),
            "num_predict": int(os.getenv("FINSPECT_OLLAMA_NUM_PREDICT", "512")),
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


def compact_json_schema(value: Any) -> Any:
    """Drop descriptive schema metadata to reduce Ollama prompt context."""
    if isinstance(value, dict):
        return {
            key: compact_json_schema(item)
            for key, item in value.items()
            if key not in {"title", "description", "default", "examples"}
        }
    if isinstance(value, list):
        return [compact_json_schema(item) for item in value]
    return value
