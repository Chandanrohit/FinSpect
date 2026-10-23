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
