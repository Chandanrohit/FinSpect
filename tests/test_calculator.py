
from decimal import Decimal

import pytest

from finspect.calculator import FormulaError, revenue_growth


def test_revenue_growth():
    result = revenue_growth(
        current=Decimal("150"),
        prior=Decimal("100"),
    )

    assert result.value == Decimal("50")
    assert result.formula_id == "Q01"
    assert result.unit == "percent"


def test_revenue_growth_handles_negative_growth():
    result = revenue_growth(
        current=Decimal("80"),
        prior=Decimal("100"),
    )

    assert result.value == Decimal("-20")
    assert result.unit == "percent"


def test_revenue_growth_rejects_zero_prior():
    with pytest.raises(FormulaError):
        revenue_growth(
            current=Decimal("150"),
            prior=Decimal("0"),
        )


def test_revenue_growth_rejects_non_finite_input():
    with pytest.raises(FormulaError):
        revenue_growth(
            current=Decimal("NaN"),
            prior=Decimal("100"),
        )


def test_revenue_growth_rejects_float_input():
    with pytest.raises(TypeError):
        revenue_growth(
            current=100.0,
            prior=Decimal("80"),
        )


def test_revenue_growth_uses_decimal_arithmetic():
    result = revenue_growth(
        current=Decimal("110"),
        prior=Decimal("80"),
    )

    assert result.value == Decimal("37.5")
