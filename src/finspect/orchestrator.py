from __future__ import annotations

import os
from functools import lru_cache
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Protocol

from finspect.answer_builder import (
    Answer,
    AnswerEvidence,
    build_calculation_answer,
    build_clarification_answer,
    build_unsupported_answer,
)
from finspect.calculator import absolute_change, revenue_growth
from finspect.edgar import company_resolver
from finspect.edgar.client import EdgarClient
from finspect.edgar.facts import FinancialFactRetriever
from finspect.query_planner import QueryPlan
from finspect.edgar.xbrl import XBRLService
from finspect.llm_planner import planner_from_environment
from finspect.plan_normalizer import normalize_query_plan
from finspect.period_resolver import (resolve_annual_period as resolve_sec_annual_period)
from finspect.edgar.fact_adapter import sec_fact_to_financial_fact
from finspect.schema import PeriodRole, ReportingScope, FinancialFact, validate_growth_inputs, validate_absolute_change_inputs
from finspect.edgar.company_resolver import (SECCompanyResolver, CompanyResolutionError)
class Planner(Protocol):
    def plan(self, question: str) -> QueryPlan:
        """Return a validated query plan."""
        ...


@dataclass(frozen=True, slots=True)
class AnnualPeriod:
    """Verified dates for one fiscal year."""

    fiscal_year: int
    start_date: str
    end_date: str
    form: str = "10-K"
    concept: str = "Revenues"
    filing_date: str | None = None
    accession_number: str | None = None

PeriodResolver = Callable[[str, int], AnnualPeriod]


@dataclass(frozen=True, slots=True)
class PipelineResult:
    plan: QueryPlan | None
    answer: Answer
    facts: tuple[dict[str, Any], ...] = ()
    canonical_facts: tuple[FinancialFact, ...] = ()

class FinSpectOrchestrator:
    """
    Coordinates planning, period resolution, SEC retrieval,
    deterministic calculation, and answer formatting.

    This first version supports annual revenue growth (Q01) only.
    """

    REVENUE_CONCEPT = (
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    )

    def __init__(
        self,
        *,
        planner: Planner,
        normalizer: Callable[[QueryPlan], QueryPlan],
        period_resolver: PeriodResolver,
        fact_retriever: FinancialFactRetriever,
        company_resolver: SECCompanyResolver | None = None,
    ) -> None:
        self.planner = planner
        self.normalizer = normalizer
        self.period_resolver = period_resolver
        self.fact_retriever = fact_retriever
        self.company_resolver = company_resolver

    def run(self, question: str) -> PipelineResult:
        question = question.strip()
        if not question:
            answer = build_unsupported_answer(
                question="",
                reason="Please enter a financial question.",
            )
            return PipelineResult(plan=None, answer=answer)

        # 1. Interpret the question with the existing LLM planner.
        plan = self.planner.plan(question)

        # 2. Apply deterministic normalization.
        plan = self.normalizer(plan)

        if plan.needs_clarification:
            answer = build_clarification_answer(
                plan.clarification_question or question
            )
            return PipelineResult(plan=plan, answer=answer)
        # Do not silently answer an absolute-change question with a rate.
        # Dollar-change calculations are not yet wired into this pipeline.

        import re
        # This first vertical slice implements Q01 only.
        is_supported_revenue_operation = (
          plan.operation in {"growth_rate", "absolute_change"}
         and any(
         metric.name.strip().casefold().replace("_", " ")
          in {"total revenue", "revenue"}
          and metric.required
          for metric in plan.metrics
           )
        )

        if not is_supported_revenue_operation:
           answer = build_unsupported_answer(
        question=question,
        reason=(
            "This FinSpect version supports annual revenue growth "
            "and absolute annual revenue change only."
          ),
       )
        return PipelineResult(plan=plan, answer=answer)
    
        fiscal_years = self._get_two_annual_years(plan)
        if fiscal_years is None:
            answer = build_unsupported_answer(
                question=question,
                reason=(
                    "Two explicit fiscal years are required for this "
                    "revenue-growth calculation."
                ),
            )
            return PipelineResult(plan=plan, answer=answer)


        # Resolve the company only when the planner did not provide a CIK.
        if plan.company.cik:
            resolved = {
                "name": plan.company.name,
                "ticker": plan.company.ticker or "",
                "cik": plan.company.cik,
            }
        elif self.company_resolver is not None:
            try:
                resolved = self.company_resolver.resolve(
                    name=plan.company.name,
                    ticker=plan.company.ticker,
                )
            except CompanyResolutionError as exc:
                answer = build_unsupported_answer(
                    question=question,
                    reason=str(exc),
                )
                return PipelineResult(plan=plan, answer=answer)
        else:
            answer = build_unsupported_answer(
                question=question,
                reason="Company resolution is unavailable and no CIK was provided.",
            )
            return PipelineResult(plan=plan, answer=answer)

        resolved_company = plan.company.model_copy(
            update={
                "name": resolved["name"],
                "ticker": resolved.get("ticker") or None,
                "cik": resolved["cik"],
            }
        )
        plan = plan.model_copy(update={"company": resolved_company})
        cik = plan.company.cik


        # 4. Resolve real reporting dates. Never guess fiscal-year dates.
        periods = [
            self.period_resolver(cik, year)
            for year in fiscal_years
        ]

        # 5. Retrieve both facts from SEC XBRL.
        facts = tuple(
            self.fact_retriever.get_fact(
                cik=cik,
                taxonomy="us-gaap",
                concept=period.concept,
                start_date=period.start_date,
                end_date=period.end_date,
                form=period.form,
                unit="USD",
                filed_on_or_before=period.filing_date,
                accession_number=period.accession_number,
            )
            for period in periods
        )

        canonical_facts = tuple(
    sec_fact_to_financial_fact(
        raw_fact,
        period_role=role,
        reporting_scope=ReportingScope.CONSOLIDATED,
    )
    for raw_fact, role in zip(
        facts,
        (PeriodRole.COMPARABLE_PRIOR, PeriodRole.CURRENT),
        strict=True,
    )
)

        # 6. Validate raw and canonical facts before calculating.
        prior_fact, current_fact = facts
        prior_canonical, current_canonical = canonical_facts

        for raw_fact, period, canonical_fact in zip(
            facts,
            periods,
            canonical_facts,
            strict=True,
        ):
            if raw_fact["start_date"] != period.start_date:
                raise ValueError(
                    "Retrieved fact has an unexpected start date."
                )

            if raw_fact["end_date"] != period.end_date:
                raise ValueError(
                    "Retrieved fact has an unexpected end date."
                )

            if raw_fact["unit"] != "USD":
                raise ValueError("Revenue facts must use USD.")

            if raw_fact["form"] != period.form:
                raise ValueError(
                    "Retrieved fact has an unexpected filing form."
                )

            if (
                period.accession_number is not None
                and raw_fact.get("accession_number")
                != period.accession_number
            ):
                raise ValueError(
                    "Retrieved fact has an unexpected accession number."
                )

            if (
                canonical_fact.period.end_date.isoformat()
                != period.end_date
            ):
                raise ValueError(
                    "Canonical fact has an unexpected end date."
                )

            if canonical_fact.concept != period.concept:
                raise ValueError(
                    "Canonical fact has an unexpected concept."
                )

        if prior_fact["end_date"] >= current_fact["end_date"]:
            raise ValueError(
                "The prior period must precede the current period."
            )

        # 7. Validate canonical inputs and calculate deterministically.
        if plan.opertion == "growth_rate":
            validate_growth_inputs(current_canonical, prior_canonical)

            calculation = revenure_growth(current=current_canonical.normalized_value, prior=prior_canonical.normalized_value)
        elif plan.operation == "absolute_change":
            validate_absolute_change_inputs(current_canonical, prior_canonical)

            calculation = absolute_change(current=current_canonical.normalized_value, prior=prior_canonical.normalized_value)
        else:
            # Defensive fallback if a future operation reaches this code.
            answer = build_unsupported_answer(question=question, reason=f"Calculation operation {plan.operation!r} is not implemented.",)
            
            return PipelineResult(plan=plan, answer=answer)
        
        # 8. Attach evidence from the actual SEC responses.
        evidence = tuple(
            AnswerEvidence(
                label=fact.get("label") or "Revenue",
                value=Decimal(str(fact["value"])),
                unit=fact["unit"],
                period=f"FY{period.fiscal_year} "
                       f"({period.start_date} to {period.end_date})",
                filing_date=fact["filing_date"],
                accession_number=fact.get("accession_number"),
                source_url=self._filing_url(fact),
            )
            for fact, period in zip(facts, periods)
        )

        answer = build_calculation_answer(
            company_name=plan.company.name,
            question=question,
            result=calculation,
            evidence=evidence,
        )

        return PipelineResult(
            plan=plan,
            answer=answer,
            facts=facts,
            canonical_facts=canonical_facts,
        )

    @staticmethod
    def _get_two_annual_years(
        plan: QueryPlan,
    ) -> tuple[int, int] | None:
        """
        Return (prior_year, current_year) only when both years
        are explicitly represented in the validated plan.
        """
        current_year = plan.period.fiscal_year
        comparison_label = plan.period.comparison_period

        if current_year is None or not comparison_label:
            return None

        # Accept labels such as FY2024 or 2024.
        import re

        match = re.fullmatch(
            r"\s*(?:FY\s*)?(\d{4})\s*",
            comparison_label,
            flags=re.IGNORECASE,
        )
        if not match:
            return None

        prior_year = int(match.group(1))
        if prior_year >= current_year:
            return None

        return prior_year, current_year

    @staticmethod
    def _filing_url(fact: dict[str, Any]) -> str | None:
        """
        Build a SEC Archives URL from the CIK and accession number.
        """
        cik = fact.get("cik")
        accession = fact.get("accession_number")

        if not cik or not accession:
            return None

        accession_without_dashes = accession.replace("-", "")
        primary_document = fact.get("primary_document")

        # The fact retriever doesn't currently return primary_document.
        # Do not fabricate a document filename.
        if not primary_document:
            return (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{int(cik)}/{accession_without_dashes}/"
            )

        return (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{accession_without_dashes}/"
            f"{primary_document}"
        )

# Entry point of Streamlit/application

@lru_cache(maxsize=1)
def get_orchestrator() -> FinSpectOrchestrator:
    """Create one configured SEC service stack per application process."""

    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise RuntimeError(
            "SEC_USER_AGENT is not configured. Set it to a descriptive "
            "FinSpect application name and a contact email."
        )

    # One HTTP client is shared by the SEC-backed services.
    client = EdgarClient(user_agent=user_agent)
    xbrl_service = XBRLService(client)
    fact_retriever = FinancialFactRetriever(xbrl_service=xbrl_service)

    def resolve_period(cik: str, fiscal_year: int) -> AnnualPeriod:
        period = resolve_sec_annual_period(
            cik,
            fiscal_year,
            xbrl_service=xbrl_service,
        )
        return AnnualPeriod(
            fiscal_year=period.fiscal_year,
            start_date=period.start_date,
            end_date=period.end_date,
            form=period.form,
            concept=period.concept,
            filing_date=period.filing_date,
            accession_number=period.accession_number,
        )

    return FinSpectOrchestrator(
        planner=planner_from_environment(),
        normalizer=normalize_query_plan,
        period_resolver=resolve_period,
        fact_retriever=fact_retriever,
        company_resolver = SECCompanyResolver(client),
    )


def run_query(question: str) -> dict[str, Any]:
    """Stable dictionary interface for the Streamlit UI."""

    result = get_orchestrator().run(question)
    answer = result.answer
    
    return {
        "answer": {
            "text": answer.text,
            "formula_id": answer.formula_id,
            "result_value": answer.result_value,
            "result_unit": answer.result_unit,
            "evidence": [
                {
                    "label": item.label,
                    "value": str(item.value),
                    "unit": item.unit,
                    "period": item.period,
                    "filing_date": item.filing_date,
                    "accession_number": item.accession_number,
                    "source_url": item.source_url,
                }
                for item in answer.evidence
            ],
            "limitations": list(answer.limitations),
        },
        "canonical_facts": [
            fact.model_dump(mode="json")
            for fact in result.canonical_facts
        ],

        "plan": (
            result.plan.model_dump(mode="json")
            if result.plan is not None
            else None
        ),
        "facts": list(result.facts),
    }
