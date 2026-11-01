from __future__ import annotations

import os
from functools import lru_cache
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Protocol

from finspect.answer_builder import (
    Answer,
    AnswerEvidence,
    build_calculation_answer,
    build_clarification_answer,
    build_unsupported_answer,
)
from finspect.calculator import (
    absolute_change,
    cash_conversion_comparison,
    earnings_change_relationship,
    growth_comparison,
    margin_change,
    revenue_growth,
)
from finspect.edgar.client import EdgarClient
from finspect.edgar.facts import FinancialFactRetriever
from finspect.query_planner import QueryPlan
from finspect.edgar.xbrl import XBRLService
from finspect.llm_planner import planner_from_environment
from finspect.plan_normalizer import normalize_query_plan
from finspect.period_resolver import (resolve_annual_period as resolve_sec_annual_period)
from finspect.edgar.fact_adapter import sec_fact_to_financial_fact
from finspect.schema import (
    PeriodRole,
    ReportingScope,
    FinancialFact,
    require_compatible_facts,
    validate_absolute_change_inputs,
    validate_currency_inputs,
    validate_growth_inputs,
    validate_instant_growth_inputs,
)
from finspect.edgar.company_resolver import (
    SECCompanyResolver,
    CompanyResolutionError,
    normalize_company_text,
)
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

    Supports annual revenue change/growth (Q01) and operating margin change (Q03).
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

        metric_names = {
            metric.name.strip().casefold().replace("_", " ")
            for metric in plan.metrics
            if metric.required
        }
        has_revenue = bool(metric_names & {"total revenue", "revenue"})
        has_receivables = bool(
            metric_names
            & {"accounts receivable", "receivables", "accounts receivable net"}
        )
        has_net_income = bool(metric_names & {"net income", "net income loss"})
        has_operating_cash_flow = bool(
            metric_names
            & {"operating cash flow", "net cash provided by operating activities"}
        )
        has_operating_income = bool(
            metric_names & {"operating income", "operating income loss"}
        )
        is_supported_revenue_operation = (
            plan.operation in {"growth_rate", "absolute_change"}
            and has_revenue
            and metric_names <= {"total revenue", "revenue"}
        )
        is_supported_margin_operation = (
            plan.operation == "margin_change"
            and has_revenue
            and has_operating_income
            and metric_names <= {
                "total revenue",
                "revenue",
                "operating income",
                "operating income loss",
            }
        )
        is_supported_receivables_operation = (
            plan.operation == "growth_comparison"
            and has_revenue
            and has_receivables
            and metric_names <= {
                "total revenue",
                "revenue",
                "accounts receivable",
                "receivables",
                "accounts receivable net",
            }
        )
        is_supported_cash_conversion = (
            plan.operation == "cash_conversion"
            and has_net_income
            and has_operating_cash_flow
            and metric_names
            <= {
                "net income",
                "net income loss",
                "operating cash flow",
                "net cash provided by operating activities",
            }
        )
        is_supported_earnings_change = (
            plan.operation == "change_relationship"
            and has_net_income
            and has_operating_income
            and metric_names
            <= {
                "net income",
                "net income loss",
                "operating income",
                "operating income loss",
            }
        )

        if not (
            is_supported_revenue_operation
            or is_supported_margin_operation
            or is_supported_receivables_operation
            or is_supported_cash_conversion
            or is_supported_earnings_change
        ):
            answer = build_unsupported_answer(
                question=question,
                reason=(
                    "This FinSpect version supports annual revenue growth, "
                    "absolute annual revenue change, and operating margin "
                    "change, annual receivables/revenue growth comparison, and "
                    "annual cash-conversion comparison plus the net-income/"
                    "operating-income change relationship."
                ),
            )
            return PipelineResult(plan=plan, answer=answer)

    
        fiscal_years = self._get_two_annual_years(plan)
        if fiscal_years is None:
            answer = build_unsupported_answer(
                question=question,
                reason=(
                    "Two explicit fiscal years are required for this "
                    "annual comparison calculation."
                ),
            )
            return PipelineResult(plan=plan, answer=answer)


        # Verify a planner-provided CIK too. Never let a CIK silently
        # override a conflicting ticker or exact company-name match.
        if self.company_resolver is not None:
            try:
                resolved = self.company_resolver.resolve(
                    name=plan.company.name,
                    ticker=plan.company.ticker,
                    cik=plan.company.cik,
                )
            except CompanyResolutionError as exc:
                answer = build_unsupported_answer(
                    question=question,
                    reason=str(exc),
                )
                return PipelineResult(plan=plan, answer=answer)
        elif plan.company.cik:
            resolved = {
                "name": plan.company.name,
                "ticker": plan.company.ticker or "",
                "cik": plan.company.cik.zfill(10),
            }
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
        for period, requested_year in zip(periods, fiscal_years, strict=True):
            self._validate_annual_period(period, requested_year)
        if date.fromisoformat(periods[1].start_date) <= date.fromisoformat(
            periods[0].end_date
        ):
            raise ValueError("Comparable annual periods must not overlap.")

        # 5. Resolve supported metrics to controlled SEC concepts, then
        # retrieve each concept for the same verified annual periods.
        concept_specs = (
            {}
            if is_supported_cash_conversion or is_supported_earnings_change
            else {"revenue": (periods[0].concept, False)}
        )
        if is_supported_margin_operation:
            concept_specs["operating_income"] = ("OperatingIncomeLoss", False)
        elif is_supported_receivables_operation:
            concept_specs["accounts_receivable"] = (
                "AccountsReceivableNetCurrent",
                True,
            )
        elif is_supported_cash_conversion:
            concept_specs["net_income"] = ("NetIncomeLoss", False)
            concept_specs["operating_cash_flow"] = (
                "NetCashProvidedByUsedInOperatingActivities",
                False,
            )
        elif is_supported_earnings_change:
            concept_specs["net_income"] = ("NetIncomeLoss", False)
            concept_specs["operating_income"] = ("OperatingIncomeLoss", False)

        raw_by_metric: dict[str, tuple[dict[str, Any], ...]] = {}
        canonical_by_metric: dict[str, tuple[FinancialFact, ...]] = {}
        roles = (PeriodRole.COMPARABLE_PRIOR, PeriodRole.CURRENT)

        for metric_name, (concept, is_instant) in concept_specs.items():
            raw_facts = tuple(
                self.fact_retriever.get_fact(
                    cik=cik,
                    taxonomy="us-gaap",
                    concept=concept,
                    start_date=None if is_instant else period.start_date,
                    end_date=period.end_date,
                    form=period.form,
                    unit="USD",
                    filed_on_or_before=period.filing_date,
                    accession_number=period.accession_number,
                )
                for period in periods
            )
            adapted_facts = tuple(
                sec_fact_to_financial_fact(
                    raw_fact,
                    period_role=role,
                    reporting_scope=ReportingScope.CONSOLIDATED,
                )
                for raw_fact, role in zip(raw_facts, roles, strict=True)
            )
            canonical_facts = tuple(
                fact.model_copy(update={"entity": resolved["name"]})
                for fact in adapted_facts
            )
            raw_by_metric[metric_name] = raw_facts
            canonical_by_metric[metric_name] = canonical_facts

            # 6. Check identity, concept, dates, units, and filing provenance
            # before any metric can reach the calculator.
            for raw_fact, period, canonical_fact in zip(
                raw_facts,
                periods,
                canonical_facts,
                strict=True,
            ):
                if str(raw_fact.get("cik", "")).zfill(10) != cik:
                    raise ValueError("Retrieved fact belongs to an unexpected CIK.")
                if normalize_company_text(
                    str(raw_fact.get("company", ""))
                ) != normalize_company_text(resolved["name"]):
                    raise ValueError(
                        "Retrieved fact company name does not match the resolved company."
                    )
                expected_start_date = None if is_instant else period.start_date
                if raw_fact.get("start_date") != expected_start_date:
                    raise ValueError("Retrieved fact has an unexpected start date.")
                if raw_fact.get("end_date") != period.end_date:
                    raise ValueError("Retrieved fact has an unexpected end date.")
                if raw_fact.get("unit") != "USD":
                    raise ValueError(f"{metric_name} facts must use USD.")
                if raw_fact.get("form") != period.form:
                    raise ValueError("Retrieved fact has an unexpected filing form.")
                if raw_fact.get("accession_number") != period.accession_number:
                    raise ValueError(
                        "Retrieved fact has an unexpected accession number."
                    )
                if canonical_fact.period.end_date.isoformat() != period.end_date:
                    raise ValueError("Canonical fact has an unexpected end date.")
                expected_kind = "instant" if is_instant else "duration"
                if canonical_fact.period.kind != expected_kind:
                    raise ValueError(
                        f"{metric_name} fact has an incompatible period kind."
                    )
                if canonical_fact.concept != concept:
                    raise ValueError("Canonical fact has an unexpected concept.")

        if plan.operation in {"growth_rate", "absolute_change"}:
            revenue_prior, revenue_current = canonical_by_metric["revenue"]
            if plan.operation == "growth_rate":
                validate_growth_inputs(revenue_current, revenue_prior)
                calculation = revenue_growth(
                    current=revenue_current.normalized_value,
                    prior=revenue_prior.normalized_value,
                )
            else:
                validate_absolute_change_inputs(revenue_current, revenue_prior)
                calculation = absolute_change(
                    current=revenue_current.normalized_value,
                    prior=revenue_prior.normalized_value,
                )
        elif is_supported_margin_operation:
            revenue_prior, revenue_current = canonical_by_metric["revenue"]
            income_prior, income_current = canonical_by_metric["operating_income"]
            validate_absolute_change_inputs(revenue_current, revenue_prior)
            validate_absolute_change_inputs(income_current, income_prior)
            require_compatible_facts(revenue_current, income_current)
            require_compatible_facts(revenue_prior, income_prior)
            validate_currency_inputs(
                revenue_current,
                revenue_prior,
                income_current,
                income_prior,
            )
            calculation = margin_change(
                current_income=income_current.normalized_value,
                current_revenue=revenue_current.normalized_value,
                prior_income=income_prior.normalized_value,
                prior_revenue=revenue_prior.normalized_value,
            )
        elif is_supported_receivables_operation:
            revenue_prior, revenue_current = canonical_by_metric["revenue"]
            receivables_prior, receivables_current = canonical_by_metric[
                "accounts_receivable"
            ]
            validate_growth_inputs(revenue_current, revenue_prior)
            validate_instant_growth_inputs(receivables_current, receivables_prior)
            if (
                receivables_current.period.end_date
                != revenue_current.period.end_date
                or receivables_prior.period.end_date != revenue_prior.period.end_date
            ):
                raise ValueError(
                    "Receivables balances must align with the revenue fiscal year ends."
                )
            require_compatible_facts(
                receivables_current,
                revenue_current,
                require_same_period=False,
            )
            require_compatible_facts(
                receivables_prior,
                revenue_prior,
                require_same_period=False,
            )
            validate_currency_inputs(
                receivables_current,
                receivables_prior,
                revenue_current,
                revenue_prior,
            )
            calculation = growth_comparison(
                ar_current=receivables_current.normalized_value,
                ar_prior=receivables_prior.normalized_value,
                revenue_current=revenue_current.normalized_value,
                revenue_prior=revenue_prior.normalized_value,
            )
        elif is_supported_cash_conversion:
            net_income_prior, net_income_current = canonical_by_metric["net_income"]
            cash_flow_prior, cash_flow_current = canonical_by_metric[
                "operating_cash_flow"
            ]
            validate_absolute_change_inputs(net_income_current, net_income_prior)
            validate_absolute_change_inputs(cash_flow_current, cash_flow_prior)
            if net_income_prior.normalized_value <= 0 or net_income_current.normalized_value <= 0:
                raise ValueError("Cash conversion requires positive net income in both periods.")
            require_compatible_facts(net_income_current, cash_flow_current)
            require_compatible_facts(net_income_prior, cash_flow_prior)
            validate_currency_inputs(
                net_income_current,
                net_income_prior,
                cash_flow_current,
                cash_flow_prior,
            )
            calculation = cash_conversion_comparison(
                operating_cash_flow_current=cash_flow_current.normalized_value,
                net_income_current=net_income_current.normalized_value,
                operating_cash_flow_prior=cash_flow_prior.normalized_value,
                net_income_prior=net_income_prior.normalized_value,
            )
        elif is_supported_earnings_change:
            net_income_prior, net_income_current = canonical_by_metric["net_income"]
            income_prior, income_current = canonical_by_metric["operating_income"]
            validate_absolute_change_inputs(net_income_current, net_income_prior)
            validate_absolute_change_inputs(income_current, income_prior)
            require_compatible_facts(net_income_current, income_current)
            require_compatible_facts(net_income_prior, income_prior)
            validate_currency_inputs(
                net_income_current,
                net_income_prior,
                income_current,
                income_prior,
            )
            calculation = earnings_change_relationship(
                net_current=net_income_current.normalized_value,
                net_prior=net_income_prior.normalized_value,
                operating_current=income_current.normalized_value,
                operating_prior=income_prior.normalized_value,
            )

        facts = tuple(
            fact
            for metric_facts in raw_by_metric.values()
            for fact in metric_facts
        )
        canonical_facts = tuple(
            fact
            for metric_facts in canonical_by_metric.values()
            for fact in metric_facts
        )

        # 7. Attach source evidence for every input actually used.
        evidence = tuple(
            AnswerEvidence(
                label=fact.get("label") or metric_name.replace("_", " ").title(),
                value=Decimal(str(fact["value"])),
                unit=fact["unit"],
                period=f"FY{period.fiscal_year} "
                       f"({period.start_date} to {period.end_date})",
                filing_date=fact["filing_date"],
                accession_number=fact.get("accession_number"),
                source_url=self._filing_url(fact),
            )
            for metric_name, raw_facts in raw_by_metric.items()
            for fact, period in zip(raw_facts, periods, strict=True)
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
    def _validate_annual_period(
        period: AnnualPeriod,
        requested_year: int,
    ) -> None:
        """Fail closed if period metadata does not substantiate an annual filing."""
        if period.fiscal_year != requested_year:
            raise ValueError(
                f"Period resolver returned FY{period.fiscal_year} for "
                f"requested FY{requested_year}."
            )
        if period.form != "10-K":
            raise ValueError("Annual revenue retrieval requires a 10-K filing.")
        if not period.start_date or not period.end_date:
            raise ValueError("Annual period must include start and end dates.")
        start = date.fromisoformat(period.start_date)
        end = date.fromisoformat(period.end_date)
        if start >= end or not 300 <= (end - start).days <= 400:
            raise ValueError("Resolved reporting period is not a full fiscal year.")
        if not period.filing_date or not period.accession_number:
            raise ValueError(
                "Annual period must include filing date and accession number."
            )
        filing_date = date.fromisoformat(period.filing_date)
        if filing_date < end:
            raise ValueError("Filing date cannot precede the reporting period end.")

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
