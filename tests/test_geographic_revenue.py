from decimal import Decimal

import pytest

from finspect.edgar.geographic_revenue import (
    GeographicRevenueError,
    GeographicRevenueExtractor,
)


def test_extracts_customer_location_revenue_and_filing_caveat():
    html = """
    <p>Revenue classified by the major geographic areas in which customers were located.</p>
    <table>
      <tr><th></th><th>2025</th><th>2024</th></tr>
      <tr><td>United States</td><td>144</td><td>124</td></tr>
      <tr><td>Other countries</td><td>137</td><td>120</td></tr>
      <tr><td>Total</td><td>281</td><td>244</td></tr>
    </table>
    <p>Includes billings to OEMs and multinational organizations when the source is impracticable to determine.</p>
    """
    result = GeographicRevenueExtractor().extract(html, fiscal_year=2025)

    assert result.basis == "customer_location"
    assert result.total_revenue == Decimal("281")
    assert result.geographic_revenue["United States"] == Decimal("144")
    assert any("impracticable" in line for line in result.limitations)


def test_extracts_billing_location_and_distinguishes_shipping_location():
    html = """
    <p>Geographic revenue is based upon customer billing location; shipping location may differ.</p>
    <table>
      <tr><th>Region</th><th>Year Ended 2025</th></tr>
      <tr><td>United States</td><td>60</td></tr>
      <tr><td>Singapore</td><td>20</td></tr>
      <tr><td>Taiwan</td><td>10</td></tr>
      <tr><td>Other</td><td>10</td></tr>
      <tr><td>Total revenue</td><td>100</td></tr>
    </table>
    <p>Singapore customers centralize invoicing while products are shipped elsewhere.</p>
    """
    result = GeographicRevenueExtractor().extract(html, fiscal_year=2025)

    assert result.basis == "billing_location"
    assert result.geographic_revenue["United States"] == Decimal("60")
    assert any("centralize invoicing" in line for line in result.limitations)


def test_rejects_geographic_table_that_does_not_reconcile():
    html = """
    <p>Revenue by geographic area (in millions).</p>
    <table>
      <tr><th></th><th>2025</th></tr>
      <tr><td>United States</td><td>70</td></tr>
      <tr><td>Other countries</td><td>20</td></tr>
      <tr><td>Total revenue</td><td>100</td></tr>
    </table>
    <p>Geographic revenue is classified based on customer billing location.</p>
    """
    with pytest.raises(GeographicRevenueError, match="reconciled"):
        GeographicRevenueExtractor().extract(html, fiscal_year=2025)


def test_prefers_more_detailed_geographic_schedule_when_filing_has_country_and_region_views():
    html = """
    <p>Geographic revenue disclosures.</p>
    <table>
      <tr><th>Country</th><th>2025</th></tr>
      <tr><td>United States</td><td>50</td></tr>
      <tr><td>Other countries</td><td>50</td></tr>
      <tr><td>Total revenue</td><td>100</td></tr>
    </table>
    <table>
      <tr><th>Region</th><th>2025</th></tr>
      <tr><td>Americas</td><td>60</td></tr>
      <tr><td>Europe</td><td>25</td></tr>
      <tr><td>Asia Pacific</td><td>15</td></tr>
      <tr><td>Total revenue</td><td>100</td></tr>
    </table>
    <p>Revenue is classified by customer location.</p>
    """
    result = GeographicRevenueExtractor().extract(html, fiscal_year=2025)

    assert result.geographic_revenue == {
        "Americas": Decimal("60"),
        "Europe": Decimal("25"),
        "Asia Pacific": Decimal("15"),
    }


def test_ignores_point_in_time_geographic_assets_when_selecting_revenue():
    html = """
    <p>Revenue classified by the major geographic areas in which customers were located.</p>
    <table>
      <tr><th></th><th>Year Ended June 30, 2025</th></tr>
      <tr><td>United States</td><td>60</td></tr>
      <tr><td>Other countries</td><td>40</td></tr>
      <tr><td>Total</td><td>100</td></tr>
    </table>
    <table>
      <tr><th></th><th>June 30, 2025</th></tr>
      <tr><td>United States</td><td>80</td></tr>
      <tr><td>Other countries</td><td>20</td></tr>
      <tr><td>Total</td><td>100</td></tr>
    </table>
    <p>Assets by major geographic area as of June 30, 2025.</p>
    <p>Revenue is classified by customer location.</p>
    """
    result = GeographicRevenueExtractor().extract(html, fiscal_year=2025)

    assert result.geographic_revenue["United States"] == Decimal("60")
