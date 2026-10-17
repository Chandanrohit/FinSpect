"""
FinSpect financial schema — Pydantic v2
Python 3.11+

Purpose
-------
1. Validate the benchmark definition (layers, Q01-Q20, primary/secondary tests).
2. Normalize extracted filing facts into reusable, typed financial sections.
3. Keep current/prior values, units, periods, scope, and evidence explicit.
4. Validate cross-field invariants before handing facts to a calculation engine.

This module intentionally does not execute formulas or interpret filing prose.
Use Decimal for all financial arithmetic. Do not use eval() on formula strings.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# =============================================================================
# Shared base and primitive types
# =============================================================================

class FSModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
    )


NonEmpty = Annotated[str, Field(min_length=1)]
Probability = Annotated[Decimal, Field(ge=0, le=1)]


class Currency(StrEnum):
    USD = "USD"
    INR = "INR"
    OTHER = "OTHER"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class UnitKind(StrEnum):
    CURRENCY = "currency"
    SHARES = "shares"
    PER_SHARE = "currency_per_share"
    PERCENT = "percent"
    PERCENTAGE_POINTS = "percentage_points"
    COUNT = "count"
    DAYS = "days"
    TEXT = "text"
    UNKNOWN = "unknown"


class ReportingScope(StrEnum):
    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"
    PARENT = "parent"
    SEGMENT = "segment"
    UNKNOWN = "unknown"


class PeriodKind(StrEnum):
    INSTANT = "instant"       # balance sheet value at a date
    DURATION = "duration"     # revenue, income, cash flow over an interval


class PeriodBasis(StrEnum):
    QUARTER = "quarter"
    THREE_MONTHS = "three_months"
    SIX_MONTHS_YTD = "six_months_ytd"
    NINE_MONTHS_YTD = "nine_months_ytd"
    FULL_YEAR = "full_year"
    POINT_IN_TIME = "point_in_time"
    CUSTOM = "custom"


class PeriodRole(StrEnum):
    CURRENT = "current"
    COMPARABLE_PRIOR = "comparable_prior"
    BEGINNING = "beginning"
    ENDING = "ending"
    OTHER = "other"


class Unit(FSModel):
    kind: UnitKind
    currency: Currency = Currency.NOT_APPLICABLE
    scale: Decimal = Decimal("1")
    label: NonEmpty

    @model_validator(mode="after")
    def check_unit(self):
        if self.scale <= 0:
            raise ValueError("Unit scale must be positive.")
        if self.kind == UnitKind.CURRENCY and self.currency == Currency.NOT_APPLICABLE:
            raise ValueError("Currency unit must specify USD, INR, or OTHER.")
        if self.kind != UnitKind.CURRENCY and self.currency not in {
            Currency.NOT_APPLICABLE, Currency.OTHER
        }:
            raise ValueError("Currency code is only valid for currency-valued units.")
        return self


class ReportingPeriod(FSModel):
    label: NonEmpty
    kind: PeriodKind
    basis: PeriodBasis
    role: PeriodRole
    start_date: date | None = None
    end_date: date
    fiscal_year: int | None = Field(default=None, ge=1900, le=2200)
    fiscal_quarter: int | None = Field(default=None, ge=1, le=4)

    @model_validator(mode="after")
    def check_period_dates(self):
        if self.kind == PeriodKind.DURATION:
            if self.start_date is None:
                raise ValueError("Duration period requires start_date.")
            if self.start_date > self.end_date:
                raise ValueError("start_date cannot be after end_date.")
        elif self.start_date is not None:
            raise ValueError("Instant period must not have start_date.")
        return self


class EvidenceRef(FSModel):
    """Traceable source for textual or structured financial evidence."""
    evidence_id: NonEmpty
    document_id: NonEmpty
    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    table: str | None = None
    row: str | None = None
    column: str | None = None
    paragraph_id: str | None = None

    # Textual evidence may have a have quote; structured XBRL evidence may not.
    quote: str | None = None
    evidence_type: Literal["direct", "context", "derived", "xbrl_fact"] = "direct"
    confidence: Probability = Decimal("1")

    # Structured SEC provenance.
    source_url: str | None = None
    accession_number: str | None = None
    taxonomy: str | None = None
    concept: str | None = None
    context_start_date: date | None = None
    context_end_date: date | None = None
    filing_date: date | None = None

    @model_validator(mode="after")
    def validate_evidence_source(self):
        has_quote = bool(self.quote and self.quote.strip())

        has_structured_source = all((
            self.accession_number,
            self.taxonomy,
            self.concept,
        ))

        if not has_quote and not has_structured_source:
            raise ValueError(
                "Evidence must contain a quote or structured source "
                "metadata (accession_number, taxonomy, concept)."
            )

        if self.evidence_type == "xbrl_fact" and not has_structured_source:
            raise ValueError(
                "XBRL evidence requires accession_number, taxonomy, "
                "and concept."
            )

        if (
            self.context_start_date is not None
            and self.context_end_date is not None
            and self.context_start_date > self.context_end_date
        ):
            raise ValueError(
                "context_start_date cannot be after context_end_date."
            )

        return self



class FilingMetadata(FSModel):
    filing_id: NonEmpty
    company_name: NonEmpty
    jurisdiction: Literal["US", "INDIA"]
    filing_type: Literal[
        "US_SEC_10Q", "US_SEC_10K",
        "INDIA_SEBI_QUARTERLY_RESULTS", "INDIA_SEBI_ANNUAL_RESULTS"
    ]
    reporting_currency: Currency
    reporting_scope: ReportingScope
    fiscal_year_end: date | None = None
    filing_date: date | None = None

    @model_validator(mode="after")
    def jurisdiction_filing_match(self):
        us = self.filing_type in {"US_SEC_10Q", "US_SEC_10K"}
        if (self.jurisdiction == "US") != us:
            raise ValueError("jurisdiction and filing_type do not match.")
        return self


# =============================================================================
# Normalized fact: the central reusable object
# =============================================================================

class FinancialFact(FSModel):
    """
    One value for one concept, entity, reporting scope, and period.
    Store the value in the unit stated by `unit`; `scale` tells how to normalize.
    Example: value=125, unit=USD millions, scale=1_000_000.
    """

    fact_id: NonEmpty
    concept: NonEmpty
    value: Decimal
    unit: Unit
    period: ReportingPeriod
    entity: NonEmpty
    scope: ReportingScope
    source_label: NonEmpty
    evidence: list[EvidenceRef] = Field(min_length=1)
    extraction_confidence: Probability = Decimal("1")
    accounting_basis: str | None = None
    is_restated: bool = False

    @property
    def normalized_value(self) -> Decimal:
        """Value expressed in base units; e.g. USD millions -> USD."""
        return self.value * self.unit.scale


class FactSet(FSModel):
    facts: list[FinancialFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_fact_ids(self):
        ids = [f.fact_id for f in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("fact_id values must be unique within a FactSet.")
        return self

    def by_concept(self, concept: str) -> list[FinancialFact]:
        return [fact for fact in self.facts if fact.concept == concept]

    def get_one(
        self,
        *,
        concept: str,
        period_role: PeriodRole,
        scope: ReportingScope | None = None,
        entity: str | None = None,
    ) -> FinancialFact:
        matches = [
            f for f in self.facts
            if f.concept == concept
            and f.period.role == period_role
            and (scope is None or f.scope == scope)
            and (entity is None or f.entity == entity)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one fact for concept={concept}, "
                f"period_role={period_role}, scope={scope}, entity={entity}; "
                f"found {len(matches)}."
            )
        return matches[0]


# =============================================================================
# Financial sections: typed views over the common facts
# =============================================================================

class PeriodValue(FSModel):
    """Reusable pair/value wrapper. The period is embedded in the fact."""
    fact: FinancialFact


class CurrentPriorValues(FSModel):
    current: PeriodValue
    prior: PeriodValue

    @model_validator(mode="after")
    def compatible_pair(self):
        current = self.current.fact
        prior = self.prior.fact
        if current.concept != prior.concept:
            raise ValueError("Current/prior pair must use the same concept.")
        if current.unit.kind != prior.unit.kind or current.unit.currency != prior.unit.currency:
            raise ValueError("Current/prior pair must use compatible units.")
        if current.scope != prior.scope:
            raise ValueError("Current/prior pair must use the same reporting scope.")
        if current.period.role != PeriodRole.CURRENT:
            raise ValueError("current value must have period role CURRENT.")
        if prior.period.role != PeriodRole.COMPARABLE_PRIOR:
            raise ValueError("prior value must have period role COMPARABLE_PRIOR.")
        return self


class RevenueSection(FSModel):
    total_revenue: CurrentPriorValues
    segment_revenue: list["SegmentRevenue"] = Field(default_factory=list)


class SegmentRevenue(FSModel):
    segment_name: NonEmpty
    current: PeriodValue
    prior: PeriodValue

    @model_validator(mode="after")
    def segment_period_concepts(self):
        c, p = self.current.fact, self.prior.fact
        if c.concept != "segment_revenue" or p.concept != "segment_revenue":
            raise ValueError("Segment values must use concept='segment_revenue'.")
        if c.entity != self.segment_name or p.entity != self.segment_name:
            raise ValueError("Segment fact entity must match segment_name.")
        if c.period.role != PeriodRole.CURRENT or p.period.role != PeriodRole.COMPARABLE_PRIOR:
            raise ValueError("Segment facts must be current and comparable-prior.")
        if c.unit.kind != p.unit.kind or c.unit.currency != p.unit.currency:
            raise ValueError("Segment current/prior units must match.")
        return self


class IncomeExpenseLine(FSModel):
    category: NonEmpty
    concept: NonEmpty
    current: PeriodValue
    prior: PeriodValue


class IncomeStatementSection(FSModel):
    revenue: CurrentPriorValues
    operating_income: CurrentPriorValues
    net_income: CurrentPriorValues
    operating_expenses: CurrentPriorValues | None = None
    expense_categories: list[IncomeExpenseLine] = Field(default_factory=list)

    @model_validator(mode="after")
    def expense_categories_are_expenses(self):
        for line in self.expense_categories:
            if line.current.fact.concept not in {"expense_category", "operating_expense_category"}:
                raise ValueError("Expense category facts must use an expense-category concept.")
            if line.prior.fact.concept not in {"expense_category", "operating_expense_category"}:
                raise ValueError("Prior expense category fact has an invalid concept.")
        return self


class EquityComponent(FSModel):
    component_name: NonEmpty
    change_amount: PeriodValue
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ShareholdersEquitySection(FSModel):
    beginning_equity: PeriodValue
    ending_equity: PeriodValue
    components: list[EquityComponent] = Field(default_factory=list)

    @model_validator(mode="after")
    def equity_period_roles(self):
        if self.beginning_equity.fact.period.role != PeriodRole.BEGINNING:
            raise ValueError("beginning_equity must use BEGINNING period role.")
        if self.ending_equity.fact.period.role != PeriodRole.ENDING:
            raise ValueError("ending_equity must use ENDING period role.")
        return self


class LiquiditySection(FSModel):
    cash_and_equivalents: CurrentPriorValues
    short_term_investments: CurrentPriorValues | None = None
    total_assets: CurrentPriorValues

    # Optional calculated field is deliberately not accepted as source data.
    # Calculate liquid assets and contribution in the calculation layer.


class CashFlowSection(FSModel):
    operating_cash_flow: CurrentPriorValues
    net_income: CurrentPriorValues
    share_repurchase_cash: CurrentPriorValues | None = None
    dividends_paid: CurrentPriorValues | None = None
    capital_expenditure_cash: CurrentPriorValues | None = None
    future_commitments: PeriodValue | None = None
    near_term_commitments: PeriodValue | None = None


class WorkingCapitalSection(FSModel):
    accounts_receivable: CurrentPriorValues | None = None
    inventory: CurrentPriorValues | None = None
    revenue: CurrentPriorValues


class ShareMetricsSection(FSModel):
    basic_weighted_average_shares: PeriodValue
    diluted_weighted_average_shares: PeriodValue
    dilutive_effect: PeriodValue | None = None

    @model_validator(mode="after")
    def share_unit_checks(self):
        facts = [
            self.basic_weighted_average_shares.fact,
            self.diluted_weighted_average_shares.fact,
        ]
        if any(f.unit.kind != UnitKind.SHARES for f in facts):
            raise ValueError("Weighted-average share facts must use SHARES units.")
        if facts[0].period != facts[1].period:
            raise ValueError("Basic and diluted weighted-average shares need the same period.")
        return self


# =============================================================================
# Qualitative disclosures and geographic / market risk
# =============================================================================

class DisclosureItem(FSModel):
    topic: NonEmpty
    summary: NonEmpty
    affected_businesses: list[str] = Field(default_factory=list)
    affected_products: list[str] = Field(default_factory=list)
    affected_geographies: list[str] = Field(default_factory=list)
    stated_uncertainty: str | None = None
    disclosed_exposure: FinancialFact | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class GeographicExposure(FSModel):
    geography: NonEmpty
    basis: Literal[
        "customer_location", "ship_to", "billing_location",
        "asset_location", "management_defined", "unspecified"
    ]
    measure: Literal["revenue", "assets", "operations", "risk", "other"]
    amount: FinancialFact | None = None
    share_of_total_percent: Decimal | None = None
    limitations: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def percentage_range(self):
        if self.share_of_total_percent is not None and not (
            Decimal("-100000") <= self.share_of_total_percent <= Decimal("100000")
        ):
            raise ValueError("Unreasonable percentage value.")
        return self


class MarketRiskSensitivity(FSModel):
    risk_type: NonEmpty
    risk_factor: NonEmpty
    scenario: NonEmpty
    sensitivity_amount: FinancialFact | None = None
    sensitivity_percent: Decimal | None = None
    reference_measure: FinancialFact | None = None
    methodology: str | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)


class RiskDisclosureSection(FSModel):
    risk_factors: list[DisclosureItem] = Field(default_factory=list)
    management_discussion: list[DisclosureItem] = Field(default_factory=list)  # MD&A / equivalent
    business_risks: list[DisclosureItem] = Field(default_factory=list)
    regulatory_and_export_risks: list[DisclosureItem] = Field(default_factory=list)
    geographic_exposures: list[GeographicExposure] = Field(default_factory=list)
    market_risk_sensitivities: list[MarketRiskSensitivity] = Field(default_factory=list)
    legal_proceedings: list[DisclosureItem] = Field(default_factory=list)
    notes_disclosures: list[DisclosureItem] = Field(default_factory=list)
    material_changes: list[DisclosureItem] = Field(default_factory=list)


# =============================================================================
# Complete normalized filing record
# =============================================================================

class FinancialStatements(FSModel):
    revenue: RevenueSection
    income_statement: IncomeStatementSection
    shareholders_equity: ShareholdersEquitySection
    liquidity: LiquiditySection
    cash_flow: CashFlowSection
    working_capital: WorkingCapitalSection
    share_metrics: ShareMetricsSection | None = None
    risks_and_disclosures: RiskDisclosureSection = Field(default_factory=RiskDisclosureSection)

    @model_validator(mode="after")
    def ensure_revenue_consistency(self):
        # The same concept should not accidentally refer to different periods/scope.
        rev_a = self.revenue.total_revenue.current.fact
        rev_b = self.income_statement.revenue.current.fact
        if rev_a.concept != rev_b.concept:
            raise ValueError("Revenue section and income statement must refer to the same concept.")
        if rev_a.period != rev_b.period or rev_a.scope != rev_b.scope:
            raise ValueError("Revenue period/scope mismatch across sections.")
        return self


class NormalizedFiling(FSModel):
    metadata: FilingMetadata
    periods: list[ReportingPeriod] = Field(min_length=1)
    statements: FinancialStatements
    all_facts: FactSet
    evidence_index: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_fact_evidence_links(self):
        evidence_ids = {e.evidence_id for e in self.evidence_index}
        # If an evidence index is supplied, every referenced evidence item must exist in it.
        if evidence_ids:
            for fact in self.all_facts.facts:
                for evidence in fact.evidence:
                    if evidence.evidence_id not in evidence_ids:
                        raise ValueError(
                            f"Fact {fact.fact_id} references evidence not in evidence_index: "
                            f"{evidence.evidence_id}"
                        )
        return self


# =============================================================================
# Benchmark schema: preserves uploaded benchmark's test taxonomy
# =============================================================================

class BenchmarkQuestion(FSModel):
    id: NonEmpty
    category: NonEmpty
    type: NonEmpty
    scope: Literal["universal", "conditional"]
    question_template: NonEmpty
    required_concepts: list[str] = Field(default_factory=list)
    required_periods: list[str] = Field(default_factory=list)
    required_disclosure: list[str] = Field(default_factory=list)
    required_sections: list[str] = Field(default_factory=list)
    preferred_evidence: list[str] = Field(default_factory=list)
    output: dict[str, Any] | None = None
    primary_test: NonEmpty
    secondary_tests: list[str] = Field(default_factory=list)
    track: Literal[
        "core_calculation", "advanced_filing_calculation", "evidence_disclosure"
    ]
    calculation: dict[str, Any] | None = None
    expected_outputs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_duplicate_tests(self):
        if self.primary_test in self.secondary_tests:
            raise ValueError(f"{self.id}: primary_test repeated in secondary_tests.")
        return self


class BenchmarkLayer(FSModel):
    layer_id: NonEmpty
    name: NonEmpty
    questions: list[BenchmarkQuestion] = Field(min_length=1)


class BenchmarkDefinition(FSModel):
    benchmark: dict[str, Any]
    layers: list[BenchmarkLayer] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        layer_ids = [layer.layer_id for layer in self.layers]
        question_ids = [q.id for layer in self.layers for q in layer.questions]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("Duplicate layer_id.")
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Duplicate question id.")
        return self

    def question_map(self) -> dict[str, BenchmarkQuestion]:
        return {q.id: q for layer in self.layers for q in layer.questions}


def load_benchmark(path: str | Path) -> BenchmarkDefinition:
    return BenchmarkDefinition.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


# =============================================================================
# Reusable validation helpers for the retrieval / calculation boundary
# =============================================================================

def require_compatible_facts(
    left: FinancialFact,
    right: FinancialFact,
    *,
    require_same_period: bool = True,
    require_same_scope: bool = True,
) -> None:
    """Call before comparing or combining two extracted facts."""
    if left.unit.kind != right.unit.kind:
        raise ValueError("Incompatible unit dimensions.")
    if left.unit.currency != right.unit.currency:
        raise ValueError("Currency mismatch; convert explicitly before calculation.")
    if require_same_period and left.period != right.period:
        raise ValueError("Period mismatch; resolve periods before calculation.")
    if require_same_scope and left.scope != right.scope:
        raise ValueError("Reporting-scope mismatch; do not mix consolidated/standalone.")



def validate_growth_inputs(current: FinancialFact, prior: FinancialFact) -> None:
    """Validate comparable financial facts before calculating growth."""
    require_compatible_facts(
        current,
        prior,
        require_same_period=False,
        require_same_scope=True,
    )

    if current.entity != prior.entity:
        raise ValueError("Entity mismatch; both facts must belong to the same entity.")

    if current.concept != prior.concept:
        raise ValueError("Concept mismatch; both facts must represent the same metric.")

    if current.period.role != PeriodRole.CURRENT:
        raise ValueError("First input must be current period.")

    if prior.period.role != PeriodRole.COMPARABLE_PRIOR:
        raise ValueError("Second input must be comparable prior period.")

    if not current.value.is_finite() or not prior.value.is_finite():
        raise ValueError("Financial fact values must be finite.")

    if current.unit.kind != prior.unit.kind:
        raise ValueError("Unit-kind mismatch.")

    if current.unit.currency != prior.unit.currency:
        raise ValueError("Currency mismatch.")

    if current.unit.scale <= 0 or prior.unit.scale <= 0:
        raise ValueError("Unit scale must be positive.")

    if current.period.kind != prior.period.kind:
        raise ValueError("Cannot compare an instant fact with a duration fact.")

    if current.period.basis != prior.period.basis:
        raise ValueError("Period basis mismatch; e.g. quarter vs full year.")

# Annual revenue growth must compare two duration periods.
    if (current.period.kind != PeriodKind.DURATION or prior.period.kind != PeriodKind.DURATION):
        raise ValueError("Revenue growth requires duration facts, not instant values.")

    if (current.period.basis != PeriodBasis.FULL_YEAR or prior.period.basis != PeriodBasis.FULL_YEAR):
        raise ValueError("Annual revenue growth requires two full-year periods.")

    if (current.period.start_date is None or prior.period.start_date is None):
        raise ValueError("Both annual facts must have reporting start dates.")


    if current.period.kind == PeriodKind.DURATION:
        if current.period.start_date is None or prior.period.start_date is None:
            raise ValueError("Duration facts require start dates.")

        if current.period.start_date <= prior.period.start_date:
            raise ValueError("Current period must start after prior period.")

        if current.period.end_date <= prior.period.end_date:
            raise ValueError("Current period must end after prior period.")

    elif current.period.end_date <= prior.period.end_date:
        raise ValueError("Current instant must be later than prior instant.")

    if prior.normalized_value == 0:
        raise ValueError("Growth rate undefined: prior-period normalized value is zero.")


def validate_currency_inputs(*facts: FinancialFact) -> None:
    if not facts:
        raise ValueError("At least one fact is required.")
    currencies = {f.unit.currency for f in facts if f.unit.kind == UnitKind.CURRENCY}
    if len(currencies) > 1:
        raise ValueError("Mixed currencies; perform explicit FX conversion first.")


def validate_required_concepts(
    facts: list[FinancialFact],
    required_concepts: list[str],
) -> list[str]:
    """Return concepts not found. Missing is not silently interpreted as zero."""
    found = {fact.concept for fact in facts}
    return [concept for concept in required_concepts if concept not in found]
