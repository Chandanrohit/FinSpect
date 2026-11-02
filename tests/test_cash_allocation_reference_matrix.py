import json
from decimal import Decimal
from pathlib import Path

import pytest

from finspect.calculator import cash_allocation


MATRIX = json.loads(
    (
        Path(__file__).parents[1]
        / "data"
        / "fixtures"
        / "annual_cash_allocation_reference_matrix.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    "case",
    MATRIX["cases"],
    ids=lambda case: f"{case['company']['ticker']}-FY{case['fiscal_year']}",
)
def test_cash_allocation_matches_annual_issuer_reference(case):
    result = cash_allocation(
        share_repurchase=Decimal(case["share_repurchase_cash"]),
        dividends=Decimal(case["dividends_paid"]),
        capex=Decimal(case["capital_expenditure"]),
        operating_cash_flow=Decimal(case["operating_cash_flow"]),
    )

    assert result.formula_id == "Q14"
    assert result.value == Decimal(case["expected_cash_allocation_percent"])
