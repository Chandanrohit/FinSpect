
from decimal import Decimal

import pytest

from finspect.calculator import FormulaError, revenue_growth, absolute_change


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


def test_absolute_change_returns_positive_currency_change():
    from finspect.calculator import absolute_change

    result = absolute_change(
        current=Decimal("130497000000"),
        prior=Decimal("60922000000"),
    )

    assert result.value == Decimal("69575000000")


def test_absolute_change_handles_decrease():
    from finspect.calculator import absolute_change

    result = absolute_change(
        current=Decimal("80"),
        prior=Decimal("100"),
    )

    assert result.value == Decimal("-20")


def test_absolute_change_handles_no_change():
    from finspect.calculator import absolute_change

    result = absolute_change(
        current=Decimal("100"),
        prior=Decimal("100"),
    )

    assert result.value == Decimal("0")


def test_absolute_change_positive():
    result = absolute_change(
        current=Decimal("125"), 
        prior=Decimal("100"),
    )
    assert result.value  == Decimal("25")
    assert result.formula_id == "ABS_CHANGE"
    assert result.unit == "currency"


def test_absolute_change_negative():
    result = absolute_change(
        current=Decimal("80"),
        prior=Decimal("100"),
    )
    assert result.value == Decimal("-20")


def test_absolute_change_zero():
    result = absolute_change(
        current=Decimal("100"),
        prior=Decimal("100"),
    )
    assert result.value == Decimal("0")


def test_absolute_change_allows_zero_prior():
    result = absolute_change(
        current=Decimal("100"),
        prior=Decimal("0"),
    )

    assert result.value == Decimal("100")


def test_absolute_change_rejects_non_finite_input():
    with pytest.raises(FormulaError):
        absolute_change(
            current=Decimal("NaN"),
            prior=Decimal("100"),
        )


def test_absolute_change_rejects_float_input():
    with pytest.raises(TypeError):
        absolute_change(
            current=100.0,
            prior=Decimal("80"),
        )