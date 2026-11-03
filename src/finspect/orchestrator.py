from __future__ import annotations

import os
from functools import lru_cache
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Protocol

from finspect.answer_builder import (
    Answer,
    AnswerEvidence,
    build_calculation_answer,
    build_clarification_answer,
    build_narrative_answer,
    build_unsupported_answer,
)
from finspect.calculator import (
    absolute_change,
    balance_change,
    cash_conversion_comparison,
    cash_allocation,
    commitment_liquidity,
    expense_growth_contribution,
    largest_increase_contributor,
    dilution_ratio,
    earnings_change_relationship,
    growth_comparison,
    liquid_asset_contribution,
    margin_change,
    revenue_growth,
    inventory_revenue_growth_comparison,
    largest_component_contribution,
    share_repurchase_comparison,
    sensitivity_ratio,
)
from finspect.edgar.client import EdgarClient
from finspect.edgar.facts import FactRetrievalError, FinancialFactRetriever
from finspect.edgar.filings import FilingRetriever, FilingRetrievalError
from finspect.edgar.parser import FilingParser
from finspect.edgar.equity_statement import (
    EquityStatementError,
    EquityStatementExtractor,
)
from finspect.edgar.commitments import CommitmentScheduleError, CommitmentScheduleExtractor
from finspect.edgar.segment_revenue import SegmentRevenueError, SegmentRevenueExtractor
from finspect.edgar.operating_expenses import (
    OperatingExpenseError,
    OperatingExpenseExtractor,
)
from finspect.edgar.geographic_revenue import (
    GeographicRevenueError,
    GeographicRevenueExtractor,
)
from finspect.edgar.market_risk import MarketRiskError, MarketRiskSensitivityExtractor
from finspect.edgar.legal import LegalDisclosureError, LegalProceedingsExtractor
from finspect.narrative_retriever import NarrativeRetriever
from finspect.material_disclosures import link_material_disclosures
from finspect.query_planner import QueryPlan
from finspect.edgar.xbrl import XBRLService
from finspect.llm_planner import planner_from_environment
from finspect.plan_normalizer import normalize_query_plan
from finspect.period_resolver import (
    resolve_annual_period as resolve_sec_annual_period,
    resolve_quarterly_period as resolve_sec_quarterly_period,
)
from finspect.edgar.fact_adapter import sec_fact_to_financial_fact
from finspect.schema import (
    PeriodBasis,
    PeriodRole,
    ReportingScope,
    FinancialFact,
    UnitKind,
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
    currency: str = "USD"

PeriodResolver = Callable[[str, int], AnnualPeriod]
QuarterPeriodResolver = Callable[[str, int, int], AnnualPeriod]


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
        quarter_period_resolver: QuarterPeriodResolver | None = None,
        fact_retriever: FinancialFactRetriever,
        company_resolver: SECCompanyResolver | None = None,
        filing_retriever: FilingRetriever | None = None,
        filing_parser: FilingParser | None = None,
        narrative_retriever: NarrativeRetriever | None = None,
    ) -> None:
        self.planner = planner
        self.normalizer = normalizer
        self.period_resolver = period_resolver
        self.quarter_period_resolver = quarter_period_resolver
        self.fact_retriever = fact_retriever
        self.company_resolver = company_resolver
        self.filing_retriever = filing_retriever
        self.filing_parser = filing_parser
        self.narrative_retriever = narrative_retriever

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
        has_inventory = bool(metric_names & {"inventory", "inventories"})
        has_net_income = bool(metric_names & {"net income", "net income loss"})
        has_operating_cash_flow = bool(
            metric_names
            & {"operating cash flow", "net cash provided by operating activities"}
        )
        has_operating_income = bool(
            metric_names & {"operating income", "operating income loss"}
        )
        has_cash_balance = bool(
            metric_names & {"cash and cash equivalents", "cash cash equivalents"}
        )
        has_short_term_investments = bool(
            metric_names
            & {
                "short term investments",
                "marketable securities",
                "short term investments or marketable securities",
            }
        )
        has_total_assets = bool(metric_names & {"assets", "total assets"})
        has_share_repurchase = bool(
            metric_names
            & {"share repurchase cash", "share repurchases", "share repurchase"}
        )
        has_dividends = bool(
            metric_names & {"dividends", "dividends paid", "cash dividends"}
        )
        has_capital_expenditure = bool(
            metric_names & {"capital expenditure", "capital expenditures", "capex"}
        )
        has_basic_shares = bool(
            metric_names & {"basic weighted average shares", "basic shares"}
        )
        has_diluted_shares = bool(
            metric_names
            & {
                "diluted weighted average shares",
                "dilutive effect",
                "dilutive effect of outstanding equity awards",
            }
        )
        has_future_commitments = bool(
            metric_names & {"future commitments", "contractual commitments", "contractual obligations", "purchase commitments"}
        )
        has_near_term_commitments = bool(
            metric_names & {"near term commitments", "near term obligations", "commitments due within one year"}
        )
        has_liquid_resources = bool(
            metric_names & {"cash and cash equivalents", "cash cash equivalents"}
        ) and bool(
            metric_names & {"short term investments", "marketable securities", "short term investments or marketable securities"}
        )
        is_supported_revenue_operation = (
            plan.operation in {"growth_rate", "absolute_change"}
            and has_revenue
            and metric_names <= {"total revenue", "revenue"}
            and (
                plan.period.period_kind == "annual"
                or (
                    plan.period.period_kind == "quarterly"
                    and plan.period.fiscal_quarter in (1, 2, 3)
                    and plan.period.comparison_required
                )
            )
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
        is_supported_inventory_operation = (
            plan.operation == "inventory_revenue_growth_comparison"
            and has_revenue and has_inventory
            and metric_names <= {"total revenue", "revenue", "inventory", "inventories"}
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
        is_supported_liquidity = (
            plan.operation == "liquidity_asset_contribution"
            and has_cash_balance
            and has_short_term_investments
            and has_total_assets
            and metric_names
            <= {
                "cash and cash equivalents",
                "cash cash equivalents",
                "short term investments",
                "marketable securities",
                "short term investments or marketable securities",
                "assets",
                "total assets",
            }
        )
        is_supported_dilution = (
            plan.operation == "dilution_ratio"
            and has_basic_shares
            and has_diluted_shares
            and metric_names
            <= {
                "basic weighted average shares",
                "basic shares",
                "diluted weighted average shares",
                "dilutive effect",
                "dilutive effect of outstanding equity awards",
            }
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
        )
        is_supported_share_repurchase = (
            plan.operation == "capital_allocation_ratio"
            and has_share_repurchase
            and has_operating_cash_flow
            and metric_names
            <= {
                "share repurchase cash",
                "share repurchases",
                "share repurchase",
                "operating cash flow",
                "net cash provided by operating activities",
            }
        )
        is_supported_equity_allocation = (
            plan.operation == "equity_component_contribution"
            and bool(metric_names & {
                "shareholders equity", "stockholders equity", "equity balance"
            })
            and bool(metric_names & {
                "equity components", "equity changes", "changes in equity"
            })
            and metric_names <= {
                "shareholders equity", "stockholders equity", "equity balance",
                "equity components", "equity changes", "changes in equity",
            }
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and not plan.period.comparison_required
        )
        is_supported_cash_allocation = (
            plan.operation == "cash_allocation"
            and has_share_repurchase
            and has_dividends
            and has_capital_expenditure
            and has_operating_cash_flow
            and metric_names <= {
                "share repurchase cash", "share repurchases", "share repurchase",
                "dividends", "dividends paid", "cash dividends",
                "capital expenditure", "capital expenditures", "capex",
                "operating cash flow", "net cash provided by operating activities",
            }
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and not plan.period.comparison_required
        )
        is_supported_equity_rollforward = (
            plan.operation == "balance_change"
            and bool(metric_names & {
                "shareholders equity", "stockholders equity", "equity balance"
            })
            and bool(metric_names & {
                "equity components", "equity changes", "changes in equity"
            })
            and metric_names <= {
                "shareholders equity", "stockholders equity", "equity balance",
                "equity components", "equity changes", "changes in equity",
            }
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and not plan.period.comparison_required
        )
        is_supported_regulatory_risk = (
            plan.operation == "regulatory_risk_analysis"
            and bool(metric_names & {
                "regulatory risk", "regulatory risks", "risk factors",
                "export control risks", "trade policy risks",
            })
            and metric_names <= {
                "regulatory risk", "regulatory risks", "risk factors",
                "export control risks", "trade policy risks",
            }
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and not plan.period.comparison_required
        )
        is_supported_geographic_exposure = (
            plan.operation == "geographic_exposure"
            and bool(metric_names & {"geographic revenue", "geographic exposure", "revenue by geography"})
            and metric_names <= {"geographic revenue", "geographic exposure", "revenue by geography"}
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and not plan.period.comparison_required
        )
        is_supported_market_risk_sensitivity = (
            plan.operation == "sensitivity_analysis"
            and bool(metric_names & {"market risk sensitivity", "interest rate sensitivity"})
            and metric_names <= {
                "market risk sensitivity", "interest rate sensitivity",
                "investment portfolio", "investment portfolio balance",
            }
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and not plan.period.comparison_required
        )
        is_supported_litigation_analysis = (
            plan.operation == "litigation_analysis"
            and bool(metric_names & {
                "litigation and contingencies", "legal proceedings", "legal proceeding",
                "litigation", "contingencies", "legal contingencies", "legal claims",
                "loss contingencies",
            })
            and metric_names <= {
                "litigation and contingencies", "legal proceedings", "legal proceeding",
                "litigation", "contingencies", "legal contingencies", "legal claims",
                "loss contingencies", "financial exposure", "loss uncertainty",
            }
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and not plan.period.comparison_required
        )
        is_supported_material_disclosure_synthesis = (
            plan.operation == "material_disclosure_synthesis"
            and bool(metric_names & {
                "material disclosures", "material disclosure synthesis",
                "material changes", "filing disclosures",
            })
            and metric_names <= {
                "material disclosures", "material disclosure synthesis",
                "material changes", "filing disclosures", "financial results",
            }
            and plan.task_type == "multi_part_analysis"
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and not plan.period.comparison_required
        )
        is_supported_commitments = (
            plan.operation == "commitment_liquidity"
            and has_future_commitments and has_near_term_commitments
            and has_liquid_resources
            and metric_names <= {
                "future commitments", "contractual commitments", "contractual obligations", "purchase commitments",
                "near term commitments", "near term obligations", "commitments due within one year",
                "cash and cash equivalents", "cash cash equivalents", "short term investments",
                "marketable securities", "short term investments or marketable securities",
            }
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and not plan.period.comparison_required
        )
        is_supported_segment_growth = (
            plan.operation == "growth_contribution"
            and bool(metric_names & {"segment revenue", "reportable segments"})
            and bool(metric_names & {"total revenue", "revenue"})
            and metric_names <= {"segment revenue", "reportable segments", "total revenue", "revenue"}
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and plan.period.comparison_required
        )
        is_supported_expense_growth = (
            plan.operation == "expense_growth_contribution"
            and bool(metric_names & {"operating expenses", "operating expense"})
            and bool(metric_names & {"expense category", "operating expense category"})
            and metric_names <= {
                "operating expenses", "operating expense",
                "expense category", "operating expense category",
            }
            and plan.period.period_kind == "annual"
            and plan.period.fiscal_year is not None
            and plan.period.comparison_required
        )

        if not (
            is_supported_revenue_operation
            or is_supported_margin_operation
            or is_supported_receivables_operation
            or is_supported_inventory_operation
            or is_supported_cash_conversion
            or is_supported_earnings_change
            or is_supported_liquidity
            or is_supported_dilution
            or is_supported_share_repurchase
            or is_supported_equity_allocation
            or is_supported_cash_allocation
            or is_supported_equity_rollforward
            or is_supported_regulatory_risk
            or is_supported_geographic_exposure
            or is_supported_market_risk_sensitivity
            or is_supported_litigation_analysis
            or is_supported_material_disclosure_synthesis
            or is_supported_commitments
            or is_supported_segment_growth
            or is_supported_expense_growth
        ):
            answer = build_unsupported_answer(
                question=question,
                reason=(
                    "This FinSpect version supports annual revenue growth, "
                    "absolute annual revenue change, and operating margin "
                    "change, annual receivables/revenue growth comparison, and "
                    "annual cash-conversion comparison plus the net-income/"
                    "operating-income change relationship, and annual liquid-"
                    "asset contribution to total asset change plus annual "
                    "weighted-average share dilution and annual share "
                    "repurchase analysis, and annual equity-change analysis "
                    "when an exact 10-K statement of equity is available, "
                    "plus annual shareholder-return and capital-expenditure "
                    "allocation when all cash-flow inputs are available. "
                    "Segment revenue contribution is supported when the exact "
                    "annual 10-K contains one reconciled reportable-segment revenue schedule. "
                    "Selected annual Item 1A risk, geographic revenue, Item 7A interest-rate sensitivity, "
                    "legal proceeding, and contingency disclosures are supported when the exact filing "
                    "contains clear evidence."
                ),
            )
            return PipelineResult(plan=plan, answer=answer)

    
        fiscal_years = self._get_two_annual_years(plan)
        if (
            is_supported_dilution
            or is_supported_equity_allocation
            or is_supported_cash_allocation
            or is_supported_equity_rollforward
            or is_supported_regulatory_risk
            or is_supported_geographic_exposure
            or is_supported_market_risk_sensitivity
            or is_supported_litigation_analysis
            or is_supported_material_disclosure_synthesis
            or is_supported_commitments
        ):
            fiscal_years = (plan.period.fiscal_year,)
        if is_supported_equity_rollforward:
            if plan.period.fiscal_year <= 1900:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The fiscal-year beginning equity period could not be determined.",
                    ),
                )
            fiscal_years = (plan.period.fiscal_year - 1, plan.period.fiscal_year)
        if is_supported_regulatory_risk:
            fiscal_years = (plan.period.fiscal_year,)
        if is_supported_geographic_exposure:
            fiscal_years = (plan.period.fiscal_year,)
        if is_supported_market_risk_sensitivity:
            fiscal_years = (plan.period.fiscal_year,)
        if is_supported_litigation_analysis:
            fiscal_years = (plan.period.fiscal_year,)
        if is_supported_commitments:
            fiscal_years = (plan.period.fiscal_year,)
        if is_supported_segment_growth:
            fiscal_years = self._get_two_annual_years(plan)
        if is_supported_expense_growth:
            fiscal_years = self._get_two_annual_years(plan)
        if fiscal_years is None:
            answer = build_unsupported_answer(
                question=question,
                reason=(
                    "An explicit fiscal year is required for annual share "
                    "dilution; two explicit fiscal years are required for "
                    "annual comparison calculations."
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
        if plan.period.period_kind == "quarterly":
            if self.quarter_period_resolver is None:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "Quarterly SEC period resolution is not configured."
                ))
            periods = [
                self.quarter_period_resolver(cik, year, plan.period.fiscal_quarter)
                for year in fiscal_years
            ]
            for period, requested_year in zip(periods, fiscal_years, strict=True):
                self._validate_quarter_period(period, requested_year, plan.period.fiscal_quarter)
        else:
            periods = [self.period_resolver(cik, year) for year in fiscal_years]
            for period, requested_year in zip(periods, fiscal_years, strict=True):
                self._validate_annual_period(period, requested_year)
        if len(periods) == 2 and date.fromisoformat(
            periods[1].start_date
        ) <= date.fromisoformat(periods[0].end_date):
            raise ValueError("Comparable annual periods must not overlap.")

        if is_supported_commitments:
            current_period = periods[0]
            if not self.filing_retriever or not self.fact_retriever:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "Exact annual filing and liquidity-fact retrieval are required for commitment analysis."
                ))
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik, accession_number=current_period.accession_number, form="10-K"
                )
                schedule = CommitmentScheduleExtractor().extract(
                    filing["html"], next_fiscal_year=current_period.fiscal_year + 1
                )
            except (FilingRetrievalError, CommitmentScheduleError, KeyError, ValueError) as exc:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, f"Could not identify one unambiguous commitment schedule in the exact 10-K: {exc}"
                ))
            if (
                filing.get("form") != "10-K"
                or str(filing.get("cik", "")).zfill(10) != cik
                or filing.get("accession_number") != current_period.accession_number
                or filing.get("filing_date") != current_period.filing_date
                or filing.get("report_date") != current_period.end_date
                or not filing.get("primary_document")
            ):
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "Retrieved commitment schedule does not match the requested issuer and exact 10-K."
                ))
            scales = {"USD": Decimal(1), "USD thousands": Decimal(1_000), "USD millions": Decimal(1_000_000)}
            if schedule.unit not in scales or current_period.currency != "USD":
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "The commitment schedule unit or filing currency could not be normalized safely to USD."
                ))

            retrieved: dict[str, FinancialFact] = {}
            for name, concepts in (
                ("cash", ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")),
                ("investments", ("MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesCurrent")),
            ):
                last_error: Exception | None = None
                for concept in concepts:
                    try:
                        raw = self.fact_retriever.get_fact(
                            cik=cik, taxonomy="us-gaap", concept=concept, start_date=None,
                            end_date=current_period.end_date, form="10-K", unit=current_period.currency,
                            filed_on_or_before=current_period.filing_date,
                            accession_number=current_period.accession_number,
                        )
                        if (
                            raw.get("cik", "").zfill(10) != cik
                            or raw.get("accession_number") != current_period.accession_number
                            or raw.get("end_date") != current_period.end_date
                            or raw.get("start_date") is not None
                        ):
                            raise FactRetrievalError("Liquidity fact does not match the exact filing period.")
                        retrieved[name] = sec_fact_to_financial_fact(
                            raw, period_role=PeriodRole.CURRENT,
                            reporting_scope=ReportingScope.CONSOLIDATED,
                        )
                        break
                    except FactRetrievalError as exc:
                        last_error = exc
                if name not in retrieved:
                    return PipelineResult(plan=plan, answer=build_unsupported_answer(
                        question, f"Could not retrieve a period-matched {name} fact: {last_error}"
                    ))
            cash, investments = retrieved["cash"], retrieved["investments"]
            try:
                require_compatible_facts(cash, investments, require_same_period=True)
                validate_currency_inputs(cash, investments)
                scale = scales[schedule.unit]
                total_commitments = schedule.total_commitments * scale
                near_commitments = schedule.next_year_commitments * scale
                liquid_resources = cash.normalized_value + investments.normalized_value
                calculation = commitment_liquidity(near_commitments, total_commitments, liquid_resources)
            except (ValueError, ArithmeticError) as exc:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, f"Commitment and liquidity inputs could not be reconciled: {exc}"
                ))
            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik, accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            evidence = [
                AnswerEvidence("Total disclosed commitments", total_commitments, "USD", f"As of {current_period.end_date}", current_period.filing_date, current_period.accession_number, filing_url),
                AnswerEvidence(f"Commitments due {current_period.fiscal_year + 1}", near_commitments, "USD", f"As of {current_period.end_date}", current_period.filing_date, current_period.accession_number, filing_url),
                AnswerEvidence("Cash and cash equivalents", cash.normalized_value, "USD", f"As of {current_period.end_date}", current_period.filing_date, current_period.accession_number, filing_url),
                AnswerEvidence("Short-term investments or marketable securities", investments.normalized_value, "USD", f"As of {current_period.end_date}", current_period.filing_date, current_period.accession_number, filing_url),
            ]
            answer = build_calculation_answer(
                company_name=resolved["name"], question=question, result=calculation,
                evidence=evidence,
                limitations=(
                    "Commitment categories and exclusions follow the issuer's selected schedule; supplemental schedules may contain additional detail.",
                    "Liquidity coverage compares reported cash and short-term investments with next-fiscal-year commitments; it is not a solvency or cash-flow forecast.",
                ),
            )
            return PipelineResult(plan=plan, answer=answer, facts=({
                "company": resolved["name"], "fiscal_year": current_period.fiscal_year,
                "total_commitments": str(total_commitments), "near_term_commitments": str(near_commitments),
                "liquid_resources": str(liquid_resources), "coverage_x": str(calculation.value),
                "accession_number": current_period.accession_number, "source_url": filing_url,
            },))

        if is_supported_segment_growth:
            current_period = periods[-1]
            if not self.filing_retriever:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "Exact 10-K retrieval is required for reportable-segment revenue analysis."
                ))
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik, accession_number=current_period.accession_number, form="10-K"
                )
                if (
                    filing.get("form") != "10-K"
                    or str(filing.get("cik", "")).zfill(10) != cik
                    or filing.get("accession_number") != current_period.accession_number
                    or filing.get("filing_date") != current_period.filing_date
                    or filing.get("report_date") != current_period.end_date
                    or not filing.get("primary_document")
                    or not filing.get("html")
                ):
                    raise FilingRetrievalError(
                        "Retrieved filing does not match the requested issuer and exact annual period."
                    )
                schedule = SegmentRevenueExtractor().extract(
                    filing["html"],
                    current_year=current_period.fiscal_year,
                    prior_year=periods[0].fiscal_year,
                )
                total_change = schedule.current_total - schedule.prior_total
                segment_changes = {
                    name: schedule.current_segments[name] - schedule.prior_segments[name]
                    for name in schedule.current_segments
                    if name in schedule.prior_segments
                }
                if sum(segment_changes.values()) != total_change:
                    raise SegmentRevenueError(
                        "Disclosed segment revenue changes do not reconcile to total revenue change."
                    )
                selected_segment, calculation = largest_increase_contributor(
                    segment_changes, total_change
                )
            except (FilingRetrievalError, SegmentRevenueError, KeyError, ValueError, ArithmeticError) as exc:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, f"Could not calculate segment revenue contribution reliably: {exc}"
                ))

            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik,
                accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            evidence = [
                AnswerEvidence(
                    f"{name} reportable-segment revenue",
                    amount,
                    schedule.unit,
                    f"FY{year}",
                    current_period.filing_date,
                    current_period.accession_number,
                    filing_url,
                )
                for values, year in (
                    (schedule.current_segments, current_period.fiscal_year),
                    (schedule.prior_segments, periods[0].fiscal_year),
                )
                for name, amount in values.items()
            ]
            evidence.extend((
                AnswerEvidence("Total revenue", schedule.current_total, schedule.unit,
                               f"FY{current_period.fiscal_year}", current_period.filing_date,
                               current_period.accession_number, filing_url),
                AnswerEvidence("Total revenue", schedule.prior_total, schedule.unit,
                               f"FY{periods[0].fiscal_year}", current_period.filing_date,
                               current_period.accession_number, filing_url),
            ))
            answer = build_calculation_answer(
                company_name=resolved["name"], question=question, result=calculation,
                evidence=evidence,
                limitations=(
                    "The calculation compares reportable-segment revenue disclosed in the selected 10-K; segment definitions can change between years.",
                    "The percentage is based on reported values from the same schedule; dollar scale cancels in the contribution ratio.",
                ),
            )
            return PipelineResult(plan=plan, answer=answer, facts=({
                "company": resolved["name"], "fiscal_year": current_period.fiscal_year,
                "prior_fiscal_year": periods[0].fiscal_year,
                "selected_segment": selected_segment,
                "segment_changes": {name: str(value) for name, value in segment_changes.items()},
                "total_revenue_change": str(total_change),
                "contribution_percent": str(calculation.value),
                "accession_number": current_period.accession_number,
                "source_url": filing_url,
            },))

        if is_supported_expense_growth:
            current_period = periods[-1]
            if not self.filing_retriever:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "Exact 10-K retrieval is required for operating-expense analysis."
                ))
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik, accession_number=current_period.accession_number, form="10-K"
                )
                if (
                    filing.get("form") != "10-K"
                    or str(filing.get("cik", "")).zfill(10) != cik
                    or filing.get("accession_number") != current_period.accession_number
                    or filing.get("filing_date") != current_period.filing_date
                    or filing.get("report_date") != current_period.end_date
                    or not filing.get("primary_document")
                    or not filing.get("html")
                ):
                    raise FilingRetrievalError(
                        "Retrieved filing does not match the requested issuer and exact annual period."
                    )
                schedule = OperatingExpenseExtractor().extract(
                    filing["html"],
                    current_year=current_period.fiscal_year,
                    prior_year=periods[0].fiscal_year,
                )
                total_change = schedule.current_total - schedule.prior_total
                category_changes = {
                    name: schedule.current_categories[name] - schedule.prior_categories[name]
                    for name in schedule.current_categories
                    if name in schedule.prior_categories
                }
                if sum(category_changes.values()) != total_change:
                    raise OperatingExpenseError(
                        "Disclosed category changes do not reconcile to operating-expense change."
                    )
                positive_changes = {
                    name: value for name, value in category_changes.items() if value > 0
                }
                if not positive_changes:
                    raise OperatingExpenseError(
                        "No disclosed operating-expense category increased."
                    )
                selected_category = max(positive_changes, key=positive_changes.__getitem__)
                calculation = expense_growth_contribution(
                    schedule.current_categories[selected_category],
                    schedule.prior_categories[selected_category],
                    schedule.current_total,
                    schedule.prior_total,
                )
                calculation = replace(
                    calculation,
                    notes=(f"selected_category={selected_category}",),
                )
            except (FilingRetrievalError, OperatingExpenseError, KeyError, ValueError, ArithmeticError) as exc:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, f"Could not calculate operating-expense contribution reliably: {exc}"
                ))

            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik,
                accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            evidence = [
                AnswerEvidence(
                    f"{name} operating-expense category",
                    amount,
                    schedule.unit,
                    f"FY{year}",
                    current_period.filing_date,
                    current_period.accession_number,
                    filing_url,
                )
                for values, year in (
                    (schedule.current_categories, current_period.fiscal_year),
                    (schedule.prior_categories, periods[0].fiscal_year),
                )
                for name, amount in values.items()
            ]
            evidence.extend((
                AnswerEvidence(
                    "Total operating expenses", schedule.current_total, schedule.unit,
                    f"FY{current_period.fiscal_year}", current_period.filing_date,
                    current_period.accession_number, filing_url,
                ),
                AnswerEvidence(
                    "Total operating expenses", schedule.prior_total, schedule.unit,
                    f"FY{periods[0].fiscal_year}", current_period.filing_date,
                    current_period.accession_number, filing_url,
                ),
            ))
            if schedule.total_method == "gross margin minus operating income":
                evidence.extend((
                    AnswerEvidence(
                        "Gross margin", schedule.current_gross_margin, schedule.unit,
                        f"FY{current_period.fiscal_year}", current_period.filing_date,
                        current_period.accession_number, filing_url,
                    ),
                    AnswerEvidence(
                        "Operating income", schedule.current_operating_income, schedule.unit,
                        f"FY{current_period.fiscal_year}", current_period.filing_date,
                        current_period.accession_number, filing_url,
                    ),
                    AnswerEvidence(
                        "Gross margin", schedule.prior_gross_margin, schedule.unit,
                        f"FY{periods[0].fiscal_year}", current_period.filing_date,
                        current_period.accession_number, filing_url,
                    ),
                    AnswerEvidence(
                        "Operating income", schedule.prior_operating_income, schedule.unit,
                        f"FY{periods[0].fiscal_year}", current_period.filing_date,
                        current_period.accession_number, filing_url,
                    ),
                ))
            answer = build_calculation_answer(
                company_name=resolved["name"], question=question, result=calculation,
                evidence=evidence,
                limitations=(
                    "Expense categories follow the issuer's presentation and may not be comparable across companies.",
                    f"The expense total was determined using {schedule.total_method}.",
                ),
            )
            return PipelineResult(plan=plan, answer=answer, facts=({
                "company": resolved["name"], "fiscal_year": current_period.fiscal_year,
                "prior_fiscal_year": periods[0].fiscal_year,
                "selected_category": selected_category,
                "category_changes": {name: str(value) for name, value in category_changes.items()},
                "total_expense_change": str(total_change),
                "contribution_percent": str(calculation.value),
                "accession_number": current_period.accession_number,
                "source_url": filing_url,
                "total_method": schedule.total_method,
            },))

        if is_supported_equity_allocation:
            current_period = periods[0]
            if not self.filing_retriever:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "Exact SEC filing retrieval is not configured for the statement of equity.",
                    ),
                )
            if not current_period.accession_number or not current_period.filing_date:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The annual period could not be tied to an exact 10-K accession and filing date.",
                    ),
                )
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik,
                    accession_number=current_period.accession_number,
                    form="10-K",
                )
            except FilingRetrievalError as exc:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        f"Could not retrieve the exact annual filing: {exc}",
                    ),
                )
            if (
                filing.get("form") != "10-K"
                or str(filing.get("cik", "")).zfill(10) != cik
                or filing.get("accession_number") != current_period.accession_number
                or filing.get("filing_date") != current_period.filing_date
                or filing.get("report_date") != current_period.end_date
            ):
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "Retrieved filing metadata does not match the requested issuer, fiscal year, and exact 10-K period.",
                    ),
                )
            if not filing.get("html") or not filing.get("primary_document"):
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The exact 10-K response did not include its filing HTML and primary document.",
                    ),
                )
            try:
                statement = EquityStatementExtractor().extract(
                    filing["html"],
                    fiscal_year=current_period.fiscal_year,
                    period_end=current_period.end_date,
                )
            except (EquityStatementError, ValueError) as exc:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        f"The exact 10-K was retrieved, but its statement of equity was not unambiguous: {exc}",
                    ),
                )
            component_name, calculation = largest_component_contribution(
                statement.components, statement.ending_equity
            )
            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik,
                accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            period_label = (
                f"FY{current_period.fiscal_year} ending {current_period.end_date}"
            )
            evidence = [
                AnswerEvidence(
                    label=label,
                    value=value,
                    unit="USD",
                    period=period_label,
                    filing_date=current_period.filing_date,
                    accession_number=current_period.accession_number,
                    source_url=filing_url,
                )
                for label, value in statement.components.items()
            ]
            evidence.append(AnswerEvidence(
                label="Ending shareholders’ equity",
                value=statement.ending_equity,
                unit="USD",
                period=period_label,
                filing_date=current_period.filing_date,
                accession_number=current_period.accession_number,
                source_url=filing_url,
            ))
            answer = build_calculation_answer(
                company_name=resolved["name"],
                question=question,
                result=calculation,
                evidence=evidence,
                limitations=(
                    "The component is the single disclosed statement row with the greatest absolute amount; separately reported rows are not aggregated.",
                    f"Amounts are read from the 10-K statement presentation ({statement.unit}) and normalized to USD.",
                ),
            )
            return PipelineResult(
                plan=plan,
                answer=answer,
                facts=({
                    "company": resolved["name"],
                    "ticker": resolved.get("ticker"),
                    "cik": cik,
                    "fiscal_year": current_period.fiscal_year,
                    "period_end": current_period.end_date,
                    "form": filing["form"],
                    "filing_date": filing["filing_date"],
                    "accession_number": filing["accession_number"],
                    "equity_components": {
                        label: str(value)
                        for label, value in statement.components.items()
                    },
                    "ending_equity": str(statement.ending_equity),
                    "unit": "USD",
                    "source_url": filing_url,
                },),
            )

        if is_supported_material_disclosure_synthesis:
            current_period = periods[0]
            required = (self.filing_retriever, self.filing_parser)
            if not all(required):
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "Exact 10-K narrative retrieval is required for this disclosure synthesis."
                ))
            if not current_period.accession_number or not current_period.filing_date:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "The requested fiscal year could not be tied to an exact 10-K accession and filing date."
                ))
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik, accession_number=current_period.accession_number, form="10-K"
                )
                if (
                    filing.get("form") != "10-K"
                    or str(filing.get("cik", "")).zfill(10) != cik
                    or filing.get("accession_number") != current_period.accession_number
                    or filing.get("filing_date") != current_period.filing_date
                    or filing.get("report_date") != current_period.end_date
                    or not filing.get("html")
                    or not filing.get("primary_document")
                ):
                    raise ValueError("Retrieved filing metadata does not match the requested issuer and fiscal year.")
                parsed = self.filing_parser.parse(filing["html"], filing_metadata=filing)
            except (FilingRetrievalError, KeyError, ValueError) as exc:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, f"Could not verify the exact 10-K for material-disclosure synthesis: {exc}"
                ))

            section_names = {
                "ITEM 7 ": "management_discussion",
                "ITEM 1A ": "risk_factors",
                "ITEM 3 ": "legal_proceedings",
                "ITEM 7A ": "market_risk",
                "ITEM 8 ": "notes",
            }
            narrative_sections: dict[str, str] = {}
            for section in parsed["sections"]:
                heading = section["heading"].upper()
                for prefix, name in section_names.items():
                    if heading.startswith(prefix):
                        narrative_sections[name] = section["text"]
                        break
            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik, accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            linked = link_material_disclosures(narrative_sections, max_themes=3)
            if not linked:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question,
                    "The exact 10-K did not yield a financial-results passage linked by a shared topic to another disclosure section; no cross-section synthesis was produced.",
                ))
            evidence_items = []
            for item in linked:
                for label, excerpt in (
                    (f"{item.theme} — MD&A", item.management_excerpt),
                    (f"{item.theme} — {item.related_section.replace('_', ' ').title()}", item.related_excerpt),
                ):
                    evidence_items.append(AnswerEvidence(
                        label, excerpt, "filing excerpt", f"FY{current_period.fiscal_year}",
                        current_period.filing_date, current_period.accession_number, filing_url,
                    ))
                if "gross margin" in item.management_excerpt.casefold():
                    for table in parsed.get("tables", []):
                        rows = table.get("rows", [])
                        flattened = " ".join(cell for row in rows for cell in row)
                        if (
                            "gross margin percentage" in flattened.casefold()
                            and "products" in flattened.casefold()
                        ):
                            table_excerpt = "; ".join(
                                " | ".join(row) for row in rows
                            )[:1200]
                            evidence_items.append(AnswerEvidence(
                                f"{item.theme} — MD&A table", table_excerpt,
                                "filing table excerpt", f"FY{current_period.fiscal_year}",
                                current_period.filing_date, current_period.accession_number,
                                filing_url,
                            ))
                            break
            evidence = tuple(evidence_items)
            limitations = (
                "Each pair links passages by shared filing language only; the related risk is not asserted to have caused the reported financial result.",
                "Quantitative amounts appear only where disclosed in the selected passages. This bounded topic search is not an exhaustive review or a definitive materiality ranking.",
            )
            answer = build_narrative_answer(
                company_name=resolved["name"], question=question,
                topic=f"candidate material financial-result and risk disclosures for FY{current_period.fiscal_year}",
                evidence=evidence, limitations=limitations,
            )
            return PipelineResult(
                plan=plan, answer=answer,
                facts=({
                    "company": resolved["name"], "ticker": resolved.get("ticker"),
                    "fiscal_year": current_period.fiscal_year,
                    "themes": [item.theme for item in linked],
                    "evidence_count": len(evidence),
                    "accession_number": current_period.accession_number,
                    "source_url": filing_url,
                },),
            )

        if is_supported_equity_rollforward:
            prior_period, current_period = periods
            if not self.filing_retriever or not self.fact_retriever:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "Exact SEC filing and equity-balance retrieval are required for an equity roll-forward.",
                    ),
                )
            if not current_period.accession_number or not current_period.filing_date:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The current annual period could not be tied to an exact 10-K accession and filing date.",
                    ),
                )
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik,
                    accession_number=current_period.accession_number,
                    form="10-K",
                )
            except FilingRetrievalError as exc:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question, f"Could not retrieve the exact annual filing: {exc}"
                    ),
                )
            if (
                filing.get("form") != "10-K"
                or str(filing.get("cik", "")).zfill(10) != cik
                or filing.get("accession_number") != current_period.accession_number
                or filing.get("filing_date") != current_period.filing_date
                or filing.get("report_date") != current_period.end_date
                or not filing.get("html")
                or not filing.get("primary_document")
            ):
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "Retrieved filing metadata or content does not match the requested issuer and exact 10-K period.",
                    ),
                )
            try:
                statement = EquityStatementExtractor().extract(
                    filing["html"],
                    fiscal_year=current_period.fiscal_year,
                    period_end=current_period.end_date,
                )
            except (EquityStatementError, ValueError) as exc:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        f"The exact 10-K did not yield an unambiguous statement of equity: {exc}",
                    ),
                )

            equity_facts: list[FinancialFact] = []
            for period, role in (
                (prior_period, PeriodRole.COMPARABLE_PRIOR),
                (current_period, PeriodRole.CURRENT),
            ):
                try:
                    raw_fact = self.fact_retriever.get_fact(
                        cik=cik,
                        taxonomy="us-gaap",
                        concept="StockholdersEquity",
                        start_date=None,
                        end_date=period.end_date,
                        form="10-K",
                        unit=period.currency,
                        filed_on_or_before=period.filing_date,
                        accession_number=period.accession_number,
                    )
                except FactRetrievalError as exc:
                    return PipelineResult(
                        plan=plan,
                        answer=build_unsupported_answer(
                            question,
                            f"Could not retrieve a period-matched shareholders’ equity balance: {exc}",
                        ),
                    )
                if (
                    raw_fact.get("cik", "").zfill(10) != cik
                    or raw_fact.get("accession_number") != period.accession_number
                    or raw_fact.get("end_date") != period.end_date
                    or raw_fact.get("start_date") is not None
                ):
                    return PipelineResult(
                        plan=plan,
                        answer=build_unsupported_answer(
                            question,
                            "A retrieved equity balance does not match the requested issuer, instant, and exact 10-K accession.",
                        ),
                    )
                equity_facts.append(
                    sec_fact_to_financial_fact(
                        raw_fact,
                        period_role=role,
                        reporting_scope=ReportingScope.CONSOLIDATED,
                    )
                )
            beginning_fact, ending_fact = equity_facts
            if (
                beginning_fact.period.kind != "instant"
                or ending_fact.period.kind != "instant"
                or ending_fact.period.end_date != date.fromisoformat(current_period.end_date)
                or beginning_fact.period.end_date != date.fromisoformat(prior_period.end_date)
            ):
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The balance-sheet facts do not match the fiscal-year start and end dates.",
                    ),
                )
            require_compatible_facts(
                beginning_fact, ending_fact, require_same_period=False
            )
            validate_currency_inputs(beginning_fact, ending_fact)
            if ending_fact.normalized_value != statement.ending_equity:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The balance-sheet equity fact conflicts with the statement-of-equity ending balance.",
                    ),
                )
            calculation = balance_change(
                ending=statement.ending_equity,
                beginning=beginning_fact.normalized_value,
                formula_id="Q06",
            )
            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik,
                accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            evidence = [
                AnswerEvidence(
                    label=label,
                    value=value,
                    unit="USD",
                    period=f"FY{current_period.fiscal_year} change",
                    filing_date=current_period.filing_date,
                    accession_number=current_period.accession_number,
                    source_url=filing_url,
                )
                for label, value in statement.components.items()
            ]
            evidence.extend((
                AnswerEvidence(
                    label="Beginning shareholders’ equity",
                    value=beginning_fact.normalized_value,
                    unit="USD",
                    period=f"As of {prior_period.end_date}",
                    filing_date=prior_period.filing_date,
                    accession_number=prior_period.accession_number,
                    source_url=self._filing_url({
                        "cik": cik,
                        "accession_number": prior_period.accession_number,
                    }),
                ),
                AnswerEvidence(
                    label="Ending shareholders’ equity",
                    value=statement.ending_equity,
                    unit="USD",
                    period=f"As of {current_period.end_date}",
                    filing_date=current_period.filing_date,
                    accession_number=current_period.accession_number,
                    source_url=filing_url,
                ),
            ))
            answer = build_calculation_answer(
                company_name=resolved["name"],
                question=question,
                result=calculation,
                evidence=evidence,
                limitations=(
                    "The displayed principal changes are individual disclosed rows; they are not aggregated and may not sum to the full balance change.",
                    f"Statement amounts reported in {statement.unit} were normalized to USD.",
                ),
            )
            return PipelineResult(
                plan=plan,
                answer=answer,
                facts=({
                    "company": resolved["name"],
                    "ticker": resolved.get("ticker"),
                    "cik": cik,
                    "fiscal_year": current_period.fiscal_year,
                    "beginning_equity": str(beginning_fact.normalized_value),
                    "ending_equity": str(statement.ending_equity),
                    "equity_change": str(calculation.value),
                    "equity_components": {
                        label: str(value)
                        for label, value in statement.components.items()
                    },
                    "accession_number": current_period.accession_number,
                    "source_url": filing_url,
                },),
            )

        if is_supported_regulatory_risk:
            current_period = periods[0]
            if not all((self.filing_retriever, self.filing_parser, self.narrative_retriever)):
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "Exact annual filing and narrative-section retrieval are required for regulatory-risk analysis.",
                    ),
                )
            if not current_period.accession_number or not current_period.filing_date:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The requested fiscal year could not be tied to an exact 10-K accession and filing date.",
                    ),
                )
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik,
                    accession_number=current_period.accession_number,
                    form="10-K",
                )
            except FilingRetrievalError as exc:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question, f"Could not retrieve the exact annual filing: {exc}"
                    ),
                )
            if (
                filing.get("form") != "10-K"
                or str(filing.get("cik", "")).zfill(10) != cik
                or filing.get("accession_number") != current_period.accession_number
                or filing.get("filing_date") != current_period.filing_date
                or filing.get("report_date") != current_period.end_date
                or not filing.get("html")
                or not filing.get("primary_document")
            ):
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "Retrieved filing metadata or content does not match the requested issuer and exact 10-K period.",
                    ),
                )
            try:
                parsed = self.filing_parser.parse(
                    filing["html"], filing_metadata=filing
                )
            except ValueError as exc:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question, f"The exact filing could not be parsed: {exc}"
                    ),
                )
            selected_sections: dict[str, str] = {}
            for section in parsed["sections"]:
                heading = section["heading"].upper()
                if heading.startswith("ITEM 1A"):
                    selected_sections["risk_factors"] = (
                        selected_sections.get("risk_factors", "")
                        + "\n\n"
                        + section["text"]
                    )
                elif heading.startswith("ITEM 1 "):
                    selected_sections["business"] = (
                        selected_sections.get("business", "")
                        + "\n\n"
                        + section["text"]
                    )
            if not selected_sections:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The exact 10-K did not expose readable Item 1 or Item 1A text for risk analysis.",
                    ),
                )
            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik,
                accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            query = (
                "regulatory export control trade government policy tariff sanctions "
                "risk and restrictions affecting products services markets customers "
                "geographic exposure operations and supply chain"
            )
            passages = self.narrative_retriever.retrieve(
                selected_sections,
                query,
                top_k=12,
                accession_number=current_period.accession_number,
                filing_url=filing_url,
            )
            risk_terms = (
                "regulat", "export control", "trade", "tariff", "sanction",
                "government polic", "restriction", "geopolit", "import control",
            )
            exposure_terms = (
                "product", "service", "market", "customer", "supply chain",
                "operation", "revenue", "sales", "business", "geographic",
            )
            relevant = []
            seen_text: set[str] = set()
            for passage in passages:
                lowered = passage.text.casefold()
                if (
                    passage.accession_number != current_period.accession_number
                    or passage.filing_url != filing_url
                    or not any(term in lowered for term in risk_terms)
                    or not any(term in lowered for term in exposure_terms)
                    or passage.text in seen_text
                ):
                    continue
                seen_text.add(passage.text)
                relevant.append(passage)
                if len(relevant) == 3:
                    break
            if not relevant:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "No relevant regulatory, trade, or export-control passage was found in the exact filing’s Item 1 or Item 1A.",
                    ),
                )
            evidence = tuple(
                AnswerEvidence(
                    label=f"Item {passage.section.replace('_', ' ')} disclosure",
                    value=passage.text,
                    unit="filing excerpt",
                    period=f"FY{current_period.fiscal_year}",
                    filing_date=current_period.filing_date,
                    accession_number=current_period.accession_number,
                    source_url=filing_url,
                )
                for passage in relevant
            )
            answer = build_narrative_answer(
                company_name=resolved["name"],
                question=question,
                topic="regulatory, trade, and export-control risk",
                evidence=evidence,
                limitations=(
                    "Keyword-ranked passages are selected excerpts, not an exhaustive legal or regulatory risk review.",
                    "The filing describes potential effects; this answer does not infer a quantified financial exposure unless the excerpt states one.",
                ),
            )
            return PipelineResult(
                plan=plan,
                answer=answer,
                facts=tuple({
                    "section": item.label,
                    "excerpt": item.value,
                    "accession_number": item.accession_number,
                    "source_url": item.source_url,
                } for item in evidence),
            )

        if is_supported_geographic_exposure:
            current_period = periods[0]
            if not self.filing_retriever:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "Exact annual filing retrieval is required for geographic revenue analysis."
                ))
            if not current_period.accession_number or not current_period.filing_date:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "The requested fiscal year could not be tied to an exact 10-K accession and filing date."
                ))
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik,
                    accession_number=current_period.accession_number,
                    form="10-K",
                )
                if (
                    filing.get("form") != "10-K"
                    or str(filing.get("cik", "")).zfill(10) != cik
                    or filing.get("accession_number") != current_period.accession_number
                    or filing.get("filing_date") != current_period.filing_date
                    or filing.get("report_date") != current_period.end_date
                    or not filing.get("html")
                    or not filing.get("primary_document")
                ):
                    raise GeographicRevenueError(
                        "Retrieved filing metadata or content does not match the requested issuer and exact 10-K period."
                    )
                schedule = GeographicRevenueExtractor().extract(
                    filing["html"], fiscal_year=current_period.fiscal_year
                )
            except (FilingRetrievalError, GeographicRevenueError, KeyError, ValueError) as exc:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, f"Could not identify one reconciled geographic-revenue schedule in the exact 10-K: {exc}"
                ))

            largest_region, largest_amount = max(
                schedule.geographic_revenue.items(), key=lambda item: item[1]
            )
            share = (largest_amount / schedule.total_revenue * Decimal(100)).quantize(
                Decimal("0.01")
            )
            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik,
                accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            evidence = (
                AnswerEvidence(
                    f"Largest disclosed geographic revenue category: {largest_region}",
                    largest_amount,
                    schedule.unit,
                    f"FY{current_period.fiscal_year}",
                    current_period.filing_date,
                    current_period.accession_number,
                    filing_url,
                ),
                AnswerEvidence(
                    "Total revenue across disclosed geographic categories",
                    schedule.total_revenue,
                    schedule.unit,
                    f"FY{current_period.fiscal_year}",
                    current_period.filing_date,
                    current_period.accession_number,
                    filing_url,
                ),
            )
            basis_text = {
                "billing_location": "customer billing location",
                "customer_location": "customer location",
                "management_defined": "the company’s reportable segment definitions",
            }.get(schedule.basis, "the filing’s stated geographic classification")
            basis_note = f"The filing classifies geography by {basis_text}."
            limitations = (basis_note, *schedule.limitations)
            answer = Answer(
                text=(
                    f"{resolved['name']} reported {largest_region} as its largest disclosed geographic "
                    f"revenue category for FY{current_period.fiscal_year}: {largest_amount:,.0f} "
                    f"{schedule.unit} of {schedule.total_revenue:,.0f} {schedule.unit}, or {share}% "
                    f"of reported revenue. The company’s classification basis and caveats are listed below.\n\n"
                    + "\n".join(f"- {item}" for item in limitations)
                    + "\n\n"
                    f"Source: [SEC Form 10-K]({filing_url})"
                ),
                formula_id=None,
                result_value=str(share),
                result_unit="percent",
                evidence=evidence,
                limitations=limitations,
            )
            return PipelineResult(
                plan=plan,
                answer=answer,
                facts=({
                    "company": resolved["name"],
                    "ticker": resolved.get("ticker"),
                    "fiscal_year": current_period.fiscal_year,
                    "largest_geography": largest_region,
                    "largest_revenue": str(largest_amount),
                    "total_revenue": str(schedule.total_revenue),
                    "share_percent": str(share),
                    "classification_basis": schedule.basis,
                    "limitations": list(schedule.limitations),
                    "accession_number": current_period.accession_number,
                    "source_url": filing_url,
                },),
            )

        if is_supported_market_risk_sensitivity:
            current_period = periods[0]
            if not self.filing_retriever or not self.fact_retriever:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question,
                    "Exact annual filing and period-matched investment-balance retrieval are required for market-risk sensitivity analysis.",
                ))
            if not current_period.accession_number or not current_period.filing_date:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question,
                    "The requested fiscal year could not be tied to an exact 10-K accession and filing date.",
                ))
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik,
                    accession_number=current_period.accession_number,
                    form="10-K",
                )
                if (
                    filing.get("form") != "10-K"
                    or str(filing.get("cik", "")).zfill(10) != cik
                    or filing.get("accession_number") != current_period.accession_number
                    or filing.get("filing_date") != current_period.filing_date
                    or filing.get("report_date") != current_period.end_date
                    or not filing.get("html")
                    or not filing.get("primary_document")
                ):
                    raise MarketRiskError(
                        "Retrieved filing metadata or content does not match the requested issuer and exact 10-K period."
                    )
                sensitivity = MarketRiskSensitivityExtractor().extract(
                    filing["html"], fiscal_year=current_period.fiscal_year
                )
            except (FilingRetrievalError, MarketRiskError, KeyError, ValueError) as exc:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, f"Could not identify one supported Item 7A sensitivity in the exact 10-K: {exc}"
                ))

            def retrieve_instant_fact(concepts: tuple[str, ...], *, required: bool):
                for concept in concepts:
                    try:
                        raw = self.fact_retriever.get_fact(
                            cik=cik,
                            taxonomy="us-gaap",
                            concept=concept,
                            start_date=None,
                            end_date=current_period.end_date,
                            form="10-K",
                            unit=current_period.currency,
                            filed_on_or_before=current_period.filing_date,
                            accession_number=current_period.accession_number,
                        )
                        if (
                            str(raw.get("cik", "")).zfill(10) != cik
                            or raw.get("accession_number") != current_period.accession_number
                            or raw.get("end_date") != current_period.end_date
                            or raw.get("start_date") is not None
                        ):
                            raise FactRetrievalError(
                                "Investment portfolio balance does not match the exact filing period."
                            )
                        return sec_fact_to_financial_fact(
                            raw,
                            period_role=PeriodRole.CURRENT,
                            reporting_scope=ReportingScope.CONSOLIDATED,
                        )
                    except FactRetrievalError:
                        continue
                if required:
                    raise FactRetrievalError(
                        f"Could not retrieve any exact-period fact for {concepts[0]}."
                    )
                return None

            try:
                cash_fact = retrieve_instant_fact((
                    "CashAndCashEquivalentsAtCarryingValue",
                    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                ), required=True)
                current_investment_fact = retrieve_instant_fact((
                    "MarketableSecuritiesCurrent",
                    "ShortTermInvestments",
                    "AvailableForSaleSecuritiesCurrent",
                ), required=True)
                noncurrent_investment_fact = retrieve_instant_fact((
                    "MarketableSecuritiesNoncurrent",
                    "AvailableForSaleSecuritiesNoncurrent",
                ), required=False)
                portfolio_facts = [cash_fact, current_investment_fact]
                if noncurrent_investment_fact is not None:
                    portfolio_facts.append(noncurrent_investment_fact)
                for left_fact, right_fact in zip(portfolio_facts, portfolio_facts[1:]):
                    require_compatible_facts(
                        left_fact, right_fact, require_same_period=True
                    )
                validate_currency_inputs(*portfolio_facts)
                if current_period.currency != "USD":
                    raise ValueError("Market-risk sensitivity ratio currently requires USD filings.")
                portfolio_value = sum(
                    fact.normalized_value for fact in portfolio_facts
                )
                sensitivity_value = sensitivity.sensitivity_amount * Decimal(1_000_000)
                calculation = sensitivity_ratio(sensitivity_value, portfolio_value)
            except (FactRetrievalError, ValueError, ArithmeticError) as exc:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, f"The sensitivity and investment portfolio could not be compared safely: {exc}"
                ))

            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik,
                accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            period_label = f"As of {current_period.end_date} (FY{current_period.fiscal_year})"
            evidence = [
                AnswerEvidence(
                    f"Item 7A hypothetical interest-rate sensitivity: {sensitivity.scenario}",
                    sensitivity_value,
                    "USD",
                    period_label,
                    current_period.filing_date,
                    current_period.accession_number,
                    filing_url,
                ),
                AnswerEvidence(
                    "Cash and cash equivalents",
                    cash_fact.normalized_value,
                    "USD",
                    period_label,
                    current_period.filing_date,
                    current_period.accession_number,
                    filing_url,
                ),
                AnswerEvidence(
                    "Current marketable securities or short-term investments",
                    current_investment_fact.normalized_value,
                    "USD",
                    period_label,
                    current_period.filing_date,
                    current_period.accession_number,
                    filing_url,
                ),
            ]
            if noncurrent_investment_fact is not None:
                evidence.append(AnswerEvidence(
                    "Noncurrent marketable securities",
                    noncurrent_investment_fact.normalized_value,
                    "USD",
                    period_label,
                    current_period.filing_date,
                    current_period.accession_number,
                    filing_url,
                ))
            evidence.append(AnswerEvidence(
                "Cash and investment portfolio balance",
                portfolio_value,
                "USD",
                period_label,
                current_period.filing_date,
                current_period.accession_number,
                filing_url,
            ))
            ratio_display = f"{calculation.value.quantize(Decimal('0.01')):,.2f}%"
            limitations = (
                "This is a hypothetical, point-in-time interest-rate scenario, not a forecast or a realized loss.",
                "The ratio compares the disclosed fair-value sensitivity with reported cash and investment balances; those balances are a contextual denominator and may include amounts outside the sensitivity model.",
                "Only the identified interest-rate investment-portfolio sensitivity is summarized; other market-risk categories may also be disclosed in Item 7A.",
            )
            answer = Answer(
                text=(
                    f"{resolved['name']} disclosed that {sensitivity.scenario} could cause a "
                    f"{sensitivity.impact} change of ${sensitivity_value:,.0f}. That equals "
                    f"{ratio_display} of its reported cash and investment portfolio balance of "
                    f"${portfolio_value:,.0f} for FY{current_period.fiscal_year}.\n\n"
                    f"Source: [SEC Form 10-K, Item 7A]({filing_url})\n\n"
                    + "\n".join(f"- {item}" for item in limitations)
                ),
                formula_id=calculation.formula_id,
                result_value=str(calculation.value),
                result_unit=calculation.unit,
                evidence=tuple(evidence),
                limitations=limitations,
            )
            return PipelineResult(
                plan=plan,
                answer=answer,
                facts=({
                    "company": resolved["name"],
                    "ticker": resolved.get("ticker"),
                    "fiscal_year": current_period.fiscal_year,
                    "scenario": sensitivity.scenario,
                    "impact": sensitivity.impact,
                    "sensitivity_amount_usd": str(sensitivity_value),
                    "portfolio_balance_usd": str(portfolio_value),
                    "ratio_percent": str(calculation.value),
                    "accession_number": current_period.accession_number,
                    "source_url": filing_url,
                },),
            )

        if is_supported_litigation_analysis:
            current_period = periods[0]
            if not self.filing_retriever:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question, "Exact annual 10-K retrieval is required for legal proceeding analysis."
                ))
            if not current_period.accession_number or not current_period.filing_date:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question,
                    "The requested fiscal year could not be tied to an exact 10-K accession and filing date.",
                ))
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik,
                    accession_number=current_period.accession_number,
                    form="10-K",
                )
                if (
                    filing.get("form") != "10-K"
                    or str(filing.get("cik", "")).zfill(10) != cik
                    or filing.get("accession_number") != current_period.accession_number
                    or filing.get("filing_date") != current_period.filing_date
                    or filing.get("report_date") != current_period.end_date
                    or not filing.get("html")
                    or not filing.get("primary_document")
                ):
                    raise LegalDisclosureError(
                        "Retrieved filing metadata or content does not match the requested issuer and exact 10-K period."
                    )
                disclosure = LegalProceedingsExtractor().extract(
                    filing["html"], fiscal_year=current_period.fiscal_year
                )
            except (FilingRetrievalError, LegalDisclosureError, KeyError, ValueError) as exc:
                return PipelineResult(plan=plan, answer=build_unsupported_answer(
                    question,
                    f"Could not identify supported legal proceeding and loss-uncertainty disclosures in the exact 10-K: {exc}",
                ))

            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik,
                accession_number=current_period.accession_number,
                primary_document=filing["primary_document"],
            )
            period_label = f"FY{current_period.fiscal_year}"
            evidence = []
            for label, excerpts in (
                ("Legal proceeding", disclosure.proceeding_excerpts[:4]),
                ("Disclosed financial exposure", disclosure.exposure_excerpts[:4]),
                ("Company-stated loss uncertainty", disclosure.uncertainty_excerpts[:3]),
            ):
                for excerpt in excerpts:
                    item = AnswerEvidence(
                        label,
                        excerpt,
                        "filing excerpt",
                        period_label,
                        current_period.filing_date,
                        current_period.accession_number,
                        filing_url,
                    )
                    if item not in evidence:
                        evidence.append(item)

            def format_excerpt_group(title: str, excerpts: tuple[str, ...], limit: int) -> str:
                if not excerpts:
                    return f"**{title}:** No clear disclosure was extracted from the selected sections."
                return "**" + title + ":**\n" + "\n".join(
                    f"- “{excerpt}”" for excerpt in excerpts[:limit]
                )

            limitations = (
                "These excerpts describe the company's disclosures as of the filing date and do not predict how a matter will be resolved.",
                "An assessed fine, an accrued liability, a possible additional loss, and an unquantified claim are different exposure categories and should not be added together.",
                "This focused extraction is not a complete legal docket or legal assessment; consult the cited filing for all proceedings and context.",
            )
            answer = Answer(
                text=(
                    f"{resolved['name']} disclosed the following selected legal proceedings and contingencies in its FY{current_period.fiscal_year} Form 10-K. The excerpts preserve the filing's descriptions of the matters, any stated amounts, and management's uncertainty language.\n\n"
                    + format_excerpt_group("Proceedings and claims", disclosure.proceeding_excerpts, 4)
                    + "\n\n"
                    + format_excerpt_group("Financial exposure disclosed", disclosure.exposure_excerpts, 4)
                    + "\n\n"
                    + format_excerpt_group("Company-stated uncertainty", disclosure.uncertainty_excerpts, 3)
                    + f"\n\nSource: [SEC Form 10-K]({filing_url})"
                    + "\n\n"
                    + "\n".join(f"- {item}" for item in limitations)
                ),
                formula_id=None,
                result_value=None,
                result_unit=None,
                evidence=tuple(evidence),
                limitations=limitations,
            )
            return PipelineResult(
                plan=plan,
                answer=answer,
                facts=({
                    "company": resolved["name"],
                    "ticker": resolved.get("ticker"),
                    "fiscal_year": current_period.fiscal_year,
                    "source_sections": list(disclosure.source_sections),
                    "proceeding_excerpts": list(disclosure.proceeding_excerpts[:4]),
                    "financial_exposure_excerpts": list(disclosure.exposure_excerpts[:4]),
                    "uncertainty_excerpts": list(disclosure.uncertainty_excerpts[:3]),
                    "accession_number": current_period.accession_number,
                    "source_url": filing_url,
                },),
            )

        # 5. Resolve supported metrics to controlled SEC concepts, then
        # retrieve each concept for the same verified annual periods.
        concept_specs = (
            {}
            if (
                is_supported_cash_conversion
                or is_supported_earnings_change
                or is_supported_liquidity
                or is_supported_dilution
                or is_supported_share_repurchase
                or is_supported_cash_allocation
            )
            else {"revenue": (periods[0].concept, False)}
        )
        if is_supported_margin_operation:
            concept_specs["operating_income"] = ("OperatingIncomeLoss", False)
        elif is_supported_receivables_operation:
            concept_specs["accounts_receivable"] = (
                "AccountsReceivableNetCurrent",
                True,
            )
        elif is_supported_inventory_operation:
            concept_specs["inventory"] = (("InventoryNet",), True)
        elif is_supported_cash_conversion:
            concept_specs["net_income"] = ("NetIncomeLoss", False)
            concept_specs["operating_cash_flow"] = (
                "NetCashProvidedByUsedInOperatingActivities",
                False,
            )
        elif is_supported_earnings_change:
            concept_specs["net_income"] = ("NetIncomeLoss", False)
            concept_specs["operating_income"] = ("OperatingIncomeLoss", False)
        elif is_supported_liquidity:
            concept_specs["cash_and_cash_equivalents"] = (
                (
                    "CashAndCashEquivalentsAtCarryingValue",
                    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                ),
                True,
            )
            concept_specs["short_term_investments"] = (
                (
                    "MarketableSecuritiesCurrent",
                    "ShortTermInvestments",
                    "AvailableForSaleSecuritiesCurrent",
                ),
                True,
            )
            concept_specs["total_assets"] = (("Assets",), True)
        elif is_supported_dilution:
            concept_specs["basic_weighted_average_shares"] = (
                ("WeightedAverageNumberOfSharesOutstandingBasic",),
                False,
            )
            concept_specs["diluted_weighted_average_shares"] = (
                ("WeightedAverageNumberOfDilutedSharesOutstanding",),
                False,
            )
        elif is_supported_share_repurchase:
            concept_specs["share_repurchase_cash"] = (
                ("PaymentsForRepurchaseOfCommonStock",),
                False,
            )
            concept_specs["operating_cash_flow"] = (
                ("NetCashProvidedByUsedInOperatingActivities",),
                False,
            )
        elif is_supported_cash_allocation:
            concept_specs["share_repurchase_cash"] = (
                ("PaymentsForRepurchaseOfCommonStock", "PaymentsRelatedToRepurchasesOfCommonStock"),
                False,
            )
            concept_specs["dividends_paid"] = (
                ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
                False,
            )
            concept_specs["capital_expenditure"] = (
                (
                    "PaymentsToAcquirePropertyPlantAndEquipment",
                    "PaymentsToAcquireProductiveAssets",
                    "PaymentsForCapitalImprovements",
                    "PaymentsRelatedToPropertyAndEquipmentAndIntangibleAssets",
                ),
                False,
            )
            concept_specs["operating_cash_flow"] = (
                ("NetCashProvidedByUsedInOperatingActivities",),
                False,
            )

        raw_by_metric: dict[str, tuple[dict[str, Any], ...]] = {}
        canonical_by_metric: dict[str, tuple[FinancialFact, ...]] = {}
        roles = (
            (PeriodRole.CURRENT,)
            if is_supported_dilution or is_supported_cash_allocation
            else (PeriodRole.COMPARABLE_PRIOR, PeriodRole.CURRENT)
        )

        for metric_name, (concept_options, is_instant) in concept_specs.items():
            concepts = (
                (concept_options,)
                if isinstance(concept_options, str)
                else tuple(concept_options)
            )
            raw_facts = None
            last_retrieval_error = None
            for concept in concepts:
                try:
                    candidate_facts = tuple(
                        self.fact_retriever.get_fact(
                            cik=cik,
                            taxonomy="us-gaap",
                            concept=concept,
                            start_date=None if is_instant else period.start_date,
                            end_date=period.end_date,
                            form=period.form,
                            unit=("shares" if is_supported_dilution else period.currency),
                            filed_on_or_before=period.filing_date,
                            accession_number=period.accession_number,
                        )
                        for period in periods
                    )
                except FactRetrievalError as exc:
                    last_retrieval_error = exc
                    continue
                raw_facts = candidate_facts
                break
            if raw_facts is None:
                if last_retrieval_error is not None:
                    raise last_retrieval_error
                raise FactRetrievalError(
                    f"No candidate SEC concept is configured for {metric_name}."
                )
            adapted_facts = tuple(
                sec_fact_to_financial_fact(
                    ({
                        **raw_fact,
                        "period_basis": PeriodBasis.QUARTER.value,
                        "fiscal_year": period.fiscal_year,
                        "fiscal_quarter": plan.period.fiscal_quarter,
                    } if plan.period.period_kind == "quarterly" else raw_fact),
                    period_role=role,
                    reporting_scope=ReportingScope.CONSOLIDATED,
                )
                for raw_fact, role, period in zip(raw_facts, roles, periods, strict=True)
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
                expected_unit = "shares" if is_supported_dilution else "USD"
                if raw_fact.get("unit") != expected_unit:
                    raise ValueError(
                        f"{metric_name} facts must use {expected_unit}."
                    )
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
        elif is_supported_inventory_operation:
            revenue_prior, revenue_current = canonical_by_metric["revenue"]
            inventory_prior, inventory_current = canonical_by_metric["inventory"]
            validate_growth_inputs(revenue_current, revenue_prior)
            validate_instant_growth_inputs(inventory_current, inventory_prior)
            if (inventory_current.period.end_date != revenue_current.period.end_date
                    or inventory_prior.period.end_date != revenue_prior.period.end_date):
                raise ValueError("Inventory balances must align with revenue fiscal year ends.")
            require_compatible_facts(inventory_current, revenue_current, require_same_period=False)
            require_compatible_facts(inventory_prior, revenue_prior, require_same_period=False)
            validate_currency_inputs(inventory_current, inventory_prior, revenue_current, revenue_prior)
            calculation = inventory_revenue_growth_comparison(
                inventory_current=inventory_current.normalized_value,
                inventory_prior=inventory_prior.normalized_value,
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
        elif is_supported_liquidity:
            cash_prior, cash_current = canonical_by_metric[
                "cash_and_cash_equivalents"
            ]
            investments_prior, investments_current = canonical_by_metric[
                "short_term_investments"
            ]
            assets_prior, assets_current = canonical_by_metric["total_assets"]
            balances = (
                cash_prior,
                cash_current,
                investments_prior,
                investments_current,
                assets_prior,
                assets_current,
            )
            if any(fact.period.kind != "instant" for fact in balances):
                raise ValueError("Q07 inputs must be instant balance-sheet facts.")
            for prior_fact, current_fact in (
                (cash_prior, cash_current),
                (investments_prior, investments_current),
                (assets_prior, assets_current),
            ):
                if (
                    prior_fact.period.end_date
                    != date.fromisoformat(periods[0].end_date)
                    or current_fact.period.end_date
                    != date.fromisoformat(periods[1].end_date)
                ):
                    raise ValueError(
                        "Q07 balances must align with the requested fiscal year ends."
                    )
            for cash_fact, investment_fact, asset_fact in (
                (cash_prior, investments_prior, assets_prior),
                (cash_current, investments_current, assets_current),
            ):
                require_compatible_facts(
                    cash_fact,
                    investment_fact,
                    require_same_period=False,
                )
                require_compatible_facts(
                    cash_fact,
                    asset_fact,
                    require_same_period=False,
                )
            validate_currency_inputs(*balances)
            calculation = liquid_asset_contribution(
                liquid_end=(
                    cash_current.normalized_value
                    + investments_current.normalized_value
                ),
                liquid_begin=(
                    cash_prior.normalized_value
                    + investments_prior.normalized_value
                ),
                assets_end=assets_current.normalized_value,
                assets_begin=assets_prior.normalized_value,
            )
        elif is_supported_dilution:
            (basic,) = canonical_by_metric["basic_weighted_average_shares"]
            (diluted,) = canonical_by_metric["diluted_weighted_average_shares"]
            if basic.period.kind != "duration" or diluted.period.kind != "duration":
                raise ValueError("Q11 inputs must be weighted-average duration facts.")
            require_compatible_facts(basic, diluted)
            if basic.unit.kind != UnitKind.SHARES or diluted.unit.kind != UnitKind.SHARES:
                raise ValueError("Q11 inputs must use share-count units.")
            calculation = dilution_ratio(
                basic.normalized_value,
                diluted.normalized_value,
            )
        elif is_supported_share_repurchase:
            repurchase_prior, repurchase_current = canonical_by_metric[
                "share_repurchase_cash"
            ]
            cash_flow_prior, cash_flow_current = canonical_by_metric[
                "operating_cash_flow"
            ]
            validate_absolute_change_inputs(repurchase_current, repurchase_prior)
            validate_absolute_change_inputs(cash_flow_current, cash_flow_prior)
            for repurchase_fact, cash_flow_fact in (
                (repurchase_prior, cash_flow_prior),
                (repurchase_current, cash_flow_current),
            ):
                require_compatible_facts(repurchase_fact, cash_flow_fact)
            validate_currency_inputs(
                repurchase_prior,
                repurchase_current,
                cash_flow_prior,
                cash_flow_current,
            )
            calculation = share_repurchase_comparison(
                current_amount=abs(repurchase_current.normalized_value),
                prior_amount=abs(repurchase_prior.normalized_value),
                current_operating_cash_flow=cash_flow_current.normalized_value,
            )
        elif is_supported_cash_allocation:
            (repurchase,) = canonical_by_metric["share_repurchase_cash"]
            (dividends,) = canonical_by_metric["dividends_paid"]
            (capex,) = canonical_by_metric["capital_expenditure"]
            (cash_flow,) = canonical_by_metric["operating_cash_flow"]
            inputs = (repurchase, dividends, capex, cash_flow)
            if any(fact.period.kind != "duration" for fact in inputs):
                raise ValueError("Q14 inputs must be annual duration facts.")
            for fact in inputs[1:]:
                require_compatible_facts(repurchase, fact)
            validate_currency_inputs(*inputs)
            calculation = cash_allocation(
                share_repurchase=abs(repurchase.normalized_value),
                dividends=abs(dividends.normalized_value),
                capex=abs(capex.normalized_value),
                operating_cash_flow=cash_flow.normalized_value,
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
                period=(
                    f"Q{plan.period.fiscal_quarter} FY{period.fiscal_year}"
                    if plan.period.period_kind == "quarterly"
                    else f"FY{period.fiscal_year}"
                ) + f" ({period.start_date} to {period.end_date})",
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
            limitations=(
                ("Uses reported cash and current short-term investments; this is not an unrestricted-cash measure.",)
                if is_supported_liquidity
                else (
                    "Capital expenditure follows the issuer’s cash-flow statement classification; some filers include intangible assets in this line.",
                )
                if is_supported_cash_allocation
                else ()
            ),
        )

        if is_supported_share_repurchase:
            metrics = calculation.metrics or {}
            current_amount = metrics["current_repurchase_amount"]
            prior_amount = metrics["prior_repurchase_amount"]
            amount_change = metrics["change_in_repurchase_amount"]
            change_text = (
                f"increased by ${amount_change:,.0f}"
                if amount_change > 0
                else f"decreased by ${abs(amount_change):,.0f}"
                if amount_change < 0
                else "was unchanged"
            )
            amount_summary = (
                f"\n\nShare repurchases were ${current_amount:,.0f} in FY{periods[1].fiscal_year} "
                f"and ${prior_amount:,.0f} in FY{periods[0].fiscal_year}; the amount "
                f"{change_text}. The FY{periods[1].fiscal_year} amount was "
                f"{metrics['current_repurchase_as_percent_of_operating_cash_flow']:.2f}% "
                "of operating cash flow. Negative cash-flow outflows are shown as "
                "positive spend magnitudes in this comparison."
            )
            if "change_in_repurchase_percent" in metrics:
                amount_summary += (
                    f" This was a {metrics['change_in_repurchase_percent']:.2f}% "
                    "change from the prior year."
                )
            answer = replace(answer, text=answer.text + amount_summary)

        if is_supported_inventory_operation:
            if not all((self.filing_retriever, self.filing_parser, self.narrative_retriever)):
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The inventory comparison was calculated, but filing narrative retrieval is not configured, so management's disclosed factors cannot be verified.",
                    ),
                    facts=facts,
                    canonical_facts=canonical_facts,
                )
            current_period = periods[1]
            try:
                filing = self.filing_retriever.get_filing(
                    cik=cik,
                    accession_number=current_period.accession_number or "",
                    form="10-K",
                )
            except FilingRetrievalError as exc:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question, f"Could not verify the exact annual filing for narrative evidence: {exc}"
                    ),
                    facts=facts,
                    canonical_facts=canonical_facts,
                )
            parsed = self.filing_parser.parse(filing["html"], filing_metadata=filing)
            narrative_sections: dict[str, str] = {}
            for section in parsed["sections"]:
                heading = section["heading"].upper()
                if heading.startswith("ITEM 7 "):
                    narrative_sections["management_discussion"] = section["text"]
                elif heading.startswith("ITEM 1A "):
                    narrative_sections["risk_factors"] = section["text"]
            filing_url = self.filing_retriever.submissions.get_filing_url(
                cik=cik,
                accession_number=current_period.accession_number or "",
                primary_document=filing["primary_document"],
            )
            passages = self.narrative_retriever.retrieve(
                narrative_sections,
                "inventory change factors demand supply product transitions excess obsolete inventory",
                top_k=5,
                accession_number=current_period.accession_number,
                filing_url=filing_url,
            )
            relevant = [
                passage for passage in passages
                if any(term in passage.text.casefold() for term in ("inventory", "inventories"))
                and passage.filing_url == filing_url
                and passage.accession_number == current_period.accession_number
            ]
            if not relevant:
                return PipelineResult(
                    plan=plan,
                    answer=build_unsupported_answer(
                        question,
                        "The exact 10-K was retrieved, but no relevant inventory factor passage was found in Item 7 or Item 1A.",
                    ),
                    facts=facts,
                    canonical_facts=canonical_facts,
                )
            excerpt_lines = [
                "Filing disclosures (verbatim excerpts; consult the filing for context):"
            ]
            for passage in relevant[:2]:
                excerpt_lines.append(
                    f"- **{passage.section.replace('_', ' ').title()}:** “{passage.text}” [SEC Form 10-K]({filing_url})"
                )
            limitation = (
                "The growth-rate difference is descriptive. These disclosures may describe possible or related drivers and do not by themselves establish that a factor caused the reported inventory change.",
            )
            answer = replace(
                answer,
                text=answer.text + "\n\n" + "\n\n".join(excerpt_lines),
                limitations=answer.limitations + limitation,
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
            r"\s*(?:Q[1-4]\s*)?(?:FY\s*)?(\d{4})\s*",
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
    def _validate_quarter_period(period: AnnualPeriod, requested_year: int, quarter: int | None) -> None:
        if period.fiscal_year != requested_year or period.form != "10-Q":
            raise ValueError("Quarter resolver returned an unexpected fiscal year or form.")
        if quarter not in (1, 2, 3) or not period.start_date or not period.end_date:
            raise ValueError("Resolved quarter must be a standalone Q1-Q3 period.")
        start, end = date.fromisoformat(period.start_date), date.fromisoformat(period.end_date)
        if start >= end or not 70 <= (end - start).days <= 110:
            raise ValueError("Quarter resolver returned a year-to-date or non-quarter duration.")
        if not period.filing_date or not period.accession_number:
            raise ValueError("Quarter period must include filing date and accession number.")
        if date.fromisoformat(period.filing_date) < end:
            raise ValueError("Filing date cannot precede the quarter end.")

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
    from finspect.edgar.submissions import SubmissionService
    filing_retriever = FilingRetriever(SubmissionService(client))

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
            currency=period.currency,
        )

    def resolve_quarter(cik: str, fiscal_year: int, quarter: int) -> AnnualPeriod:
        return resolve_sec_quarterly_period(
            cik, fiscal_year, quarter, xbrl_service=xbrl_service
        )

    return FinSpectOrchestrator(
        planner=planner_from_environment(),
        normalizer=normalize_query_plan,
        period_resolver=resolve_period,
        quarter_period_resolver=resolve_quarter,
        fact_retriever=fact_retriever,
        company_resolver = SECCompanyResolver(client),
        filing_retriever=filing_retriever,
        filing_parser=FilingParser(),
        narrative_retriever=NarrativeRetriever(),
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
