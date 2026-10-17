
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finspect.schema import (
    Currency,
    EvidenceRef,
    FinancialFact,
    PeriodBasis,
    PeriodKind,
    PeriodRole,
    ReportingPeriod,
    ReportingScope,
    Unit,
    UnitKind,
    validate_growth_inputs,
)


def make_fact(
    *,
    fact_id: str,
    value: str,
    role: PeriodRole,
    currency: Currency = Currency.USD,
    basis: PeriodBasis = PeriodBasis.FULL_YEAR,
) -> FinancialFact:
    """Build a valid revenue fact for validator tests."""
    period = ReportingPeriod(
        label=f"{role.value} fiscal year",
        kind=PeriodKind.DURATION,
        basis=basis,
        role=role,
        start_date=date(2024, 1, 1) if role != PeriodRole.COMPARABLE_PRIOR
        else date(2023, 1, 1),
        end_date=date(2024, 12, 31) if role != PeriodRole.COMPARABLE_PRIOR
        else date(2023, 12, 31),
        fiscal_year=2024 if role != PeriodRole.COMPARABLE_PRIOR else 2023,
    )

    return FinancialFact(
        fact_id=fact_id,
        concept="revenue",
        value=Decimal(value),
        unit=Unit(
            kind=UnitKind.CURRENCY,
            currency=currency,
            scale=Decimal("1"),
            label=f"{currency.value}",
        ),
        period=period,
        entity="Example Company",
        scope=ReportingScope.CONSOLIDATED,
        source_label="Total revenue",
        evidence=[
            EvidenceRef(
                evidence_id=f"evidence-{fact_id}",
                document_id="test-filing",
                quote="Total revenue reported in the filing",
            )
        ],
    )


def test_unit_rejects_zero_scale():
    with pytest.raises(ValidationError):
        Unit(
            kind=UnitKind.CURRENCY,
            currency=Currency.USD,
            scale=Decimal("0"),
            label="USD",
        )


def test_growth_inputs_accept_comparable_revenue_facts():
    current = make_fact(
        fact_id="current-revenue",
        value="150",
        role=PeriodRole.CURRENT,
    )
    prior = make_fact(
        fact_id="prior-revenue",
        value="100",
        role=PeriodRole.COMPARABLE_PRIOR,
    )

    # No exception means the inputs passed validation.
    validate_growth_inputs(current, prior)


def test_growth_inputs_reject_zero_prior_value():
    current = make_fact(
        fact_id="current-revenue",
        value="150",
        role=PeriodRole.CURRENT,
    )
    prior = make_fact(
        fact_id="prior-revenue",
        value="0",
        role=PeriodRole.COMPARABLE_PRIOR,
    )

    with pytest.raises(ValueError, match="zero"):
        validate_growth_inputs(current, prior)


def test_growth_inputs_reject_currency_mismatch():
    current = make_fact(
        fact_id="current-revenue",
        value="150",
        role=PeriodRole.CURRENT,
        currency=Currency.USD,
    )
    prior = make_fact(
        fact_id="prior-revenue",
        value="100",
        role=PeriodRole.COMPARABLE_PRIOR,
        currency=Currency.INR,
    )

    with pytest.raises(ValueError, match="Currency mismatch"):
        validate_growth_inputs(current, prior)


def test_growth_inputs_reject_quarter_vs_full_year():
    current = make_fact(
        fact_id="current-revenue",
        value="150",
        role=PeriodRole.CURRENT,
        basis=PeriodBasis.QUARTER,
    )
    prior = make_fact(
        fact_id="prior-revenue",
        value="100",
        role=PeriodRole.COMPARABLE_PRIOR,
        basis=PeriodBasis.FULL_YEAR,
    )

    with pytest.raises(ValueError, match="basis mismatch"):
        validate_growth_inputs(current, prior)


def test_growth_inputs_reject_entity_mismatch():
    current = make_fact(
        fact_id="current",
        value="150",
        role=PeriodRole.CURRENT,
    )
    prior = make_fact(
        fact_id="prior",
        value="100",
        role=PeriodRole.COMPARABLE_PRIOR,
    )
    prior.entity = "Different Company"

    with pytest.raises(ValueError, match="Entity mismatch"):
        validate_growth_inputs(current, prior)


def test_growth_inputs_reject_non_finite_values():
    with pytest.raises(ValidationError):
        make_fact(
            fact_id="current",
            value="NaN",
            role=PeriodRole.CURRENT,
        )


def test_growth_inputs_reject_non_chronological_periods():
    current = make_fact(
        fact_id="current",
        value="150",
        role=PeriodRole.CURRENT,
    )
    prior = make_fact(
        fact_id="prior",
        value="100",
        role=PeriodRole.COMPARABLE_PRIOR,
    )

    # Deliberately make the current period earlier than the prior period.
    current.period.start_date = date(2022, 1, 1)
    current.period.end_date = date(2022, 12, 31)

    with pytest.raises(ValueError, match="Current period must"):
        validate_growth_inputs(current, prior)
