
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

# Reuse the strict Pydantic base from your existing schema module.
from finspect.schema import FSModel


# =============================================================================
# Controlled vocabulary
# =============================================================================

BenchmarkID = Literal[
    "Q01", "Q02", "Q03", "Q04", "Q05",
    "Q06", "Q07", "Q08", "Q09", "Q10",
    "Q11", "Q12", "Q13", "Q14", "Q15",
    "Q16", "Q17", "Q18", "Q19", "Q20",
]

TaskType = Literal[
    "calculation",
    "comparison",
    "disclosure_analysis",
    "multi_part_analysis",
    "clarification",
]

RetrievalSource = Literal[
    "xbrl",
    "financial_table",
    "narrative",
    "segment_disclosure",
    "notes",
    "risk_factors",
    "legal_proceedings",
    "market_risk",
]

Operation = Literal[
    "growth_rate",
    "growth_contribution",
    "margin_change",
    "expense_growth_contribution",
    "change_relationship",
    "balance_change",
    "liquidity_asset_contribution",
    "growth_comparison",
    "inventory_revenue_growth_comparison",
    "capital_allocation_ratio",
    "dilution_ratio",
    "equity_component_contribution",
    "cash_conversion",
    "cash_allocation",
    "commitment_liquidity",
    "regulatory_risk_analysis",
    "geographic_exposure",
    "sensitivity_analysis",
    "litigation_analysis",
    "material_disclosure_synthesis",
    "other",
]


# =============================================================================
# Company and reporting period
# =============================================================================

class CompanyRequest(FSModel):
    """Company identity as expressed or resolved from the user query."""

    name: str = Field(min_length=1)
    ticker: str | None = None
    cik: str | None = Field(
        default=None,
        pattern=r"^\d{1,10}$",
    )


class PeriodRequest(FSModel):
    """
    Requested period, not a claim that a filing has already been found.

    Use explicit dates when known. Fiscal labels such as FY2025 can be
    retained until the filing resolver identifies actual reporting dates.
    """

    period_label: str | None = None

    period_kind: Literal[
        "annual",
        "quarterly",
        "instant",
        "unspecified",
    ] = "unspecified"

    fiscal_year: int | None = Field(
        default=None,
        ge=1900,
        le=2200,
    )

    fiscal_quarter: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )

    comparison_required: bool = False
    comparison_period: str | None = None

    @model_validator(mode="after")
    def validate_period(self):
        if self.fiscal_quarter is not None:
            if self.period_kind != "quarterly":
                raise ValueError(
                    "fiscal_quarter requires period_kind='quarterly'."
                )

        if self.comparison_period and not self.comparison_required:
            raise ValueError(
                "A comparison_period requires comparison_required=True."
            )

        if self.period_kind == "annual" and self.fiscal_quarter is not None:
            raise ValueError(
                "An annual period cannot specify a fiscal quarter."
            )

        return self


# =============================================================================
# Requested metrics and retrieval
# =============================================================================

class MetricRequest(FSModel):
    """One concept needed to answer the question."""

    name: str = Field(min_length=1)

    role: Literal[
        "primary",
        "comparison",
        "supporting",
        "denominator",
        "context",
    ]

    sources: list[RetrievalSource] = Field(min_length=1)

    required: bool = True

    # Optional hint for concept mapping. This is not an SEC fact value.
    concept_hint: str | None = None


class RetrievalRequirements(FSModel):
    """Instructions for evidence retrieval, not retrieved evidence itself."""

    sources: list[RetrievalSource] = Field(min_length=1)

    preferred_sections: list[str] = Field(default_factory=list)

    require_direct_evidence: bool = True

    require_period_and_unit_metadata: bool = True

    max_evidence_items: int = Field(default=8, ge=1, le=30)


class AnswerRequirements(FSModel):
    """What the final answer should contain."""

    include_conclusion: bool = True
    include_formula: bool = False
    include_input_values: bool = True
    include_periods: bool = True
    include_units: bool = True
    include_citations: bool = True
    include_limitations: bool = True

    # Examples: percentage, percentage_points, currency, text.
    expected_output: Literal[
        "percentage",
        "percentage_points",
        "currency",
        "ratio",
        "count",
        "text",
        "mixed",
        "unspecified",
    ] = "unspecified"


# =============================================================================
# Query plan
# =============================================================================

class QueryPlan(FSModel):
    """
    Validated interpretation of a user's financial question.

    This model contains instructions only. Retrieved values, source evidence,
    calculation results, and final prose belong to later pipeline stages.
    """

    original_question: str = Field(min_length=1)

    company: CompanyRequest

    period: PeriodRequest = Field(default_factory=PeriodRequest)

    benchmark_id: BenchmarkID | None = None

    task_type: TaskType

    metrics: list[MetricRequest] = Field(min_length=1)

    operation: Operation

    retrieval: RetrievalRequirements

    answer: AnswerRequirements = Field(
        default_factory=AnswerRequirements
    )

    needs_clarification: bool = False

    clarification_question: str | None = None

    # Optional explanation for logs/debugging, not a source of truth.
    planning_note: str | None = None

    @model_validator(mode="after")
    def validate_plan_consistency(self):
        if self.needs_clarification and not self.clarification_question:
            raise ValueError(
                "clarification_question is required when "
                "needs_clarification=True."
            )

        if (
            self.task_type == "clarification"
            and not self.needs_clarification
        ):
            raise ValueError(
                "task_type='clarification' requires "
                "needs_clarification=True."
            )

        if (
            self.task_type == "disclosure_analysis"
            and self.operation in {
                "growth_rate",
                "growth_contribution",
                "margin_change",
                "expense_growth_contribution",
                "change_relationship",
                "balance_change",
                "liquidity_asset_contribution",
                "growth_comparison",
                "inventory_revenue_growth_comparison",
                "capital_allocation_ratio",
                "dilution_ratio",
                "equity_component_contribution",
                "cash_conversion",
                "cash_allocation",
                "commitment_liquidity",
                "sensitivity_analysis",
            }
        ):
            raise ValueError(
                "A calculation operation cannot be the primary "
                "operation for disclosure_analysis."
            )

        if (
            self.operation == "material_disclosure_synthesis"
            and self.task_type != "multi_part_analysis"
        ):
            raise ValueError(
                "material_disclosure_synthesis requires "
                "task_type='multi_part_analysis'."
            )

        return self


# =============================================================================
# Safe serialization helper
# =============================================================================

def parse_query_plan(payload: dict) -> QueryPlan:
    """
    Validate a dictionary produced by the LLM.

    Raises pydantic.ValidationError if the model returns malformed data.
    Never executes code or accepts arbitrary calculator function names.
    """
    return QueryPlan.model_validate(payload)
