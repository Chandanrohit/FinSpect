
from decimal import Decimal

from finspect.calculator import revenue_growth


def test_revenue_growth():
    result = revenue_growth(
        current=Decimal("150"),
        prior=Decimal("100"),
    )

    assert result.value == Decimal("50")
    assert result.formula_id == "Q01"
    assert result.unit == "percent"


import pytest

from finspect.calculator import FormulaError, revenue_growth


def test_revenue_growth():
    from decimal import Decimal

    result = revenue_growth(
        current=Decimal("150"),
        prior=Decimal("100"),
    )

    assert result.value == Decimal("50")
    assert result.formula_id == "Q01"
    assert result.unit == "percent"


def test_revenue_growth_rejects_zero_prior():
    from decimal import Decimal

    with pytest.raises(FormulaError):
        revenue_growth(
            current=Decimal("150"),
            prior=Decimal("0"),
        )
