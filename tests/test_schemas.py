
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
    validate_instant_growth_inputs,
)


def make_fact(
    *,
    fact_id: str,
    value: str,
    role: PeriodRole,
    currency: Currency = Currency.USD,
    currency_label: str | None = None,
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
            label=currency_label or currency.value,
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
        basis=PeriodBasis.FULL_YEAR,
    )
    prior = make_fact(
        fact_id="prior-revenue",
        value="100",
        role=PeriodRole.COMPARABLE_PRIOR,
        basis=PeriodBasis.FULL_YEAR,
    )

    # Both are full-year revenue facts for the same company and currency.
    # Validation should succeed without raising an exception.
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

    current.period.start_date = date(2022, 1, 1)
    current.period.end_date = date(2022, 12, 31)

    with pytest.raises(ValueError, match="start after prior period"):
        validate_growth_inputs(current, prior)


def test_growth_inputs_reject_negative_prior_denominator():
    current = make_fact(
        fact_id="current-revenue",
        value="150",
        role=PeriodRole.CURRENT,
    )
    prior = make_fact(
        fact_id="prior-revenue",
        value="-100",
        role=PeriodRole.COMPARABLE_PRIOR,
    )

    with pytest.raises(ValueError, match="prior-period amount must be positive"):
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


def test_growth_inputs_reject_different_currencies_marked_other():
    current = make_fact(
        fact_id="current-revenue",
        value="150",
        role=PeriodRole.CURRENT,
        currency=Currency.OTHER,
        currency_label="EUR",
    )
    prior = make_fact(
        fact_id="prior-revenue",
        value="100",
        role=PeriodRole.COMPARABLE_PRIOR,
        currency=Currency.OTHER,
        currency_label="GBP",
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


def test_instant_growth_inputs_accept_comparable_balance_sheet_facts():
    current = make_fact(
        fact_id="ar-current",
        value="23065",
        role=PeriodRole.CURRENT,
    )
    prior = make_fact(
        fact_id="ar-prior",
        value="9999",
        role=PeriodRole.COMPARABLE_PRIOR,
    )
    current = current.model_copy(update={
        "concept": "AccountsReceivableNetCurrent",
        "period": ReportingPeriod(
            label="FY2025 ending balance",
            kind=PeriodKind.INSTANT,
            basis=PeriodBasis.POINT_IN_TIME,
            role=PeriodRole.CURRENT,
            end_date=date(2025, 1, 26),
            fiscal_year=2025,
        ),
    })
    prior = prior.model_copy(update={
        "concept": "AccountsReceivableNetCurrent",
        "period": ReportingPeriod(
            label="FY2024 ending balance",
            kind=PeriodKind.INSTANT,
            basis=PeriodBasis.POINT_IN_TIME,
            role=PeriodRole.COMPARABLE_PRIOR,
            end_date=date(2024, 1, 28),
            fiscal_year=2024,
        ),
    })

    validate_instant_growth_inputs(current, prior)


def test_instant_growth_inputs_reject_zero_prior_balance():
    current = make_fact(
        fact_id="ar-current",
        value="23065",
        role=PeriodRole.CURRENT,
    )
    prior = make_fact(
        fact_id="ar-prior",
        value="0",
        role=PeriodRole.COMPARABLE_PRIOR,
    )
    current = current.model_copy(update={
        "concept": "AccountsReceivableNetCurrent",
        "period": ReportingPeriod(
            label="FY2025 ending balance",
            kind=PeriodKind.INSTANT,
            basis=PeriodBasis.POINT_IN_TIME,
            role=PeriodRole.CURRENT,
            end_date=date(2025, 1, 26),
            fiscal_year=2025,
        ),
    })
    prior = prior.model_copy(update={
        "concept": "AccountsReceivableNetCurrent",
        "period": ReportingPeriod(
            label="FY2024 ending balance",
            kind=PeriodKind.INSTANT,
            basis=PeriodBasis.POINT_IN_TIME,
            role=PeriodRole.COMPARABLE_PRIOR,
            end_date=date(2024, 1, 28),
            fiscal_year=2024,
        ),
    })

    with pytest.raises(ValueError, match="Growth rate undefined"):
        validate_instant_growth_inputs(current, prior)


def test_instant_growth_inputs_reject_negative_prior_balance():
    current = make_fact(
        fact_id="ar-current",
        value="23065",
        role=PeriodRole.CURRENT,
    )
    prior = make_fact(
        fact_id="ar-prior",
        value="-9999",
        role=PeriodRole.COMPARABLE_PRIOR,
    )
    current = current.model_copy(update={
        "concept": "AccountsReceivableNetCurrent",
        "period": ReportingPeriod(
            label="FY2025 ending balance",
            kind=PeriodKind.INSTANT,
            basis=PeriodBasis.POINT_IN_TIME,
            role=PeriodRole.CURRENT,
            end_date=date(2025, 1, 26),
            fiscal_year=2025,
        ),
    })
    prior = prior.model_copy(update={
        "concept": "AccountsReceivableNetCurrent",
        "period": ReportingPeriod(
            label="FY2024 ending balance",
            kind=PeriodKind.INSTANT,
            basis=PeriodBasis.POINT_IN_TIME,
            role=PeriodRole.COMPARABLE_PRIOR,
            end_date=date(2024, 1, 28),
            fiscal_year=2024,
        ),
    })

    with pytest.raises(ValueError, match="prior balance must be positive"):
        validate_instant_growth_inputs(current, prior)
