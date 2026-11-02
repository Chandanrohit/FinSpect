import json
from decimal import Decimal
from pathlib import Path

import pytest

from finspect.calculator import balance_change


MATRIX = json.loads(
    (
        Path(__file__).parents[1]
        / "data"
        / "fixtures"
        / "annual_equity_rollforward_reference_matrix.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    "case",
    MATRIX["cases"],
    ids=lambda case: f"{case['company']['ticker']}-FY{case['fiscal_year']}",
)
def test_equity_rollforward_matches_annual_reference(case):
    result = balance_change(
        ending=Decimal(case["ending_equity"]),
        beginning=Decimal(case["beginning_equity"]),
        formula_id="Q06",
    )

    assert result.value == Decimal(case["expected_equity_change"])
