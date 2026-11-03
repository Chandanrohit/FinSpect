from decimal import Decimal

import pytest

from finspect.edgar.market_risk import (
    MarketRiskError,
    MarketRiskSensitivityExtractor,
)


def test_extracts_narrative_yield_curve_sensitivity():
    html = """
    <p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p>
    <p>Interest rate risk. As of the end of fiscal year 2025, parallel shifts in the yield curve of
    plus or minus 0.5% would result in a change in fair value for these
    investments of $238 million.</p>
    <p>Item 8. Financial Statements</p>
    """
    result = MarketRiskSensitivityExtractor().extract(html, fiscal_year=2025)

    assert result.sensitivity_amount == Decimal("238")
    assert result.unit == "USD millions"
    assert "plus or minus 0.5%" in result.scenario
    assert result.table_index is None


def test_extracts_latest_year_interest_rate_sensitivity_from_market_risk_table():
    html = """
    <p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p>
    <p>Interest rate risk. Sensitivity analysis of fair-value exposure under hypothetical market changes.</p>
    <table>
      <tr><th>(In millions)</th></tr>
      <tr><th>Risk Categories</th><th>Hypothetical Change</th><th>June 30, 2025</th><th>Impact</th></tr>
      <tr><td>Interest rate</td><td>100 basis point increase in Treasury rates</td><td>(1,415)</td><td>Fair Value</td></tr>
      <tr><td>Credit</td><td>100 basis point increase in spreads</td><td>(436)</td><td>Fair Value</td></tr>
    </table>
    <p>Item 8. Financial Statements</p>
    """
    result = MarketRiskSensitivityExtractor().extract(html, fiscal_year=2025)

    assert result.sensitivity_amount == Decimal("1415")
    assert result.impact == "fair value of fixed-income portfolio"
    assert "basis point" in result.scenario


def test_extracts_investment_portfolio_row_by_fiscal_year():
    html = """
    <p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p>
    <p>Interest rate risk. Potential impacts of hypothetical interest-rate changes (dollars in millions).</p>
    <table>
      <tr><th>Instrument</th><th>Hypothetical Interest Rate Increase</th><th>Potential Impact</th><th>2025</th><th>2024</th></tr>
      <tr><td>Investment portfolio</td><td>100 basis points, all tenors</td><td>Decline in fair value</td><td>2,416</td><td>2,755</td></tr>
      <tr><td>Term debt</td><td>100 basis points, all tenors</td><td>Increase in annual interest expense</td><td>129</td><td>139</td></tr>
    </table>
    <p>Item 8. Financial Statements</p>
    """
    result = MarketRiskSensitivityExtractor().extract(html, fiscal_year=2025)

    assert result.sensitivity_amount == Decimal("2416")
    assert result.impact == "fair value of investment portfolio"
    assert result.scenario == "100 basis points, all tenors"


def test_fails_closed_when_item7a_has_no_supported_numeric_sensitivity():
    html = """
    <p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p>
    <p>Interest rates may affect the fair value of investments, but no amount is quantified.</p>
    <p>Item 8. Financial Statements</p>
    """
    with pytest.raises(MarketRiskError, match="found 0"):
        MarketRiskSensitivityExtractor().extract(html, fiscal_year=2025)


def test_does_not_take_market_risk_sensitivity_from_tables_after_item7a():
    html = """
    <p>ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK</p>
    <p>We discuss general interest rate risk but disclose no quantitative investment sensitivity here.</p>
    <p>ITEM 8. FINANCIAL STATEMENTS</p>
    <p>Supplemental table</p>
    <table><tr><th>Instrument</th><th>Hypothetical Interest Rate Increase</th><th>Potential Impact</th><th>2025</th></tr>
    <tr><td>Investment portfolio</td><td>100 basis points, all tenors</td><td>Decline in fair value</td><td>2,416</td></tr></table>
    """
    with pytest.raises(MarketRiskError, match="found 0"):
        MarketRiskSensitivityExtractor().extract(html, fiscal_year=2025)
