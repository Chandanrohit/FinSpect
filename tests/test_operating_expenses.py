from decimal import Decimal

import pytest

from finspect.edgar.operating_expenses import (
    OperatingExpenseError,
    OperatingExpenseExtractor,
)


def test_extracts_explicit_operating_expense_total_and_categories():
    html = """
    <p>Operating expenses (in millions)</p>
    <table>
      <tr><th></th><th>2025</th><th>2024</th></tr>
      <tr><td>Operating Expenses:</td><td></td><td></td></tr>
      <tr><td>Research and development</td><td>35</td><td>31</td></tr>
      <tr><td>Selling and administrative</td><td>27</td><td>26</td></tr>
      <tr><td>Total operating expenses</td><td>62</td><td>57</td></tr>
      <tr><td>Year-over-year Percentage Change:</td><td></td><td></td></tr>
      <tr><td>Research and development</td><td>13</td><td>8</td></tr>
    </table>
    """
    result = OperatingExpenseExtractor().extract(
        html, current_year=2025, prior_year=2024
    )

    assert result.current_total == Decimal("62")
    assert result.prior_total == Decimal("57")
    assert result.current_categories["Research and development"] == Decimal("35")
    assert result.total_method == "reported total operating expenses"


def test_derives_total_from_gross_margin_and_operating_income():
    html = """
    <table>
      <tr><th></th><th>2025</th><th>2024</th></tr>
      <tr><td>Gross margin</td><td>194</td><td>171</td></tr>
      <tr><td>Research and development</td><td>32</td><td>29</td></tr>
      <tr><td>Sales and marketing</td><td>25</td><td>24</td></tr>
      <tr><td>General and administrative</td><td>7</td><td>8</td></tr>
      <tr><td>Operating income</td><td>130</td><td>110</td></tr>
    </table>
    """
    result = OperatingExpenseExtractor().extract(
        html, current_year=2025, prior_year=2024
    )

    assert result.current_total == Decimal("64")
    assert result.prior_total == Decimal("61")
    assert result.prior_categories["General and administrative"] == Decimal("8")
    assert result.total_method == "gross margin minus operating income"


def test_rejects_categories_that_do_not_reconcile_to_reported_total():
    html = """
    <table>
      <tr><th></th><th>2025</th><th>2024</th></tr>
      <tr><td>Operating expenses</td><td></td><td></td></tr>
      <tr><td>Category A</td><td>40</td><td>30</td></tr>
      <tr><td>Category B</td><td>20</td><td>20</td></tr>
      <tr><td>Total operating expenses</td><td>70</td><td>50</td></tr>
    </table>
    """
    with pytest.raises(OperatingExpenseError, match="reconciled"):
        OperatingExpenseExtractor().extract(html, current_year=2025, prior_year=2024)
