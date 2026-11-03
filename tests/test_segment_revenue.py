from decimal import Decimal

import pytest

from finspect.edgar.segment_revenue import (
    SegmentRevenueError,
    SegmentRevenueExtractor,
)


def test_extracts_reportable_segments_from_direct_year_columns():
    html = """
    <p>The following table shows net sales by reportable segment (dollars in millions).</p>
    <table>
      <tr><th></th><th>2025</th><th>Change</th><th>2024</th></tr>
      <tr><td>Americas</td><td>$178,353</td><td>7%</td><td>$167,045</td></tr>
      <tr><td>Europe</td><td>111,032</td><td>10%</td><td>101,328</td></tr>
      <tr><td>Greater China</td><td>64,377</td><td>(4)%</td><td>66,952</td></tr>
      <tr><td>Japan</td><td>28,703</td><td>15%</td><td>25,052</td></tr>
      <tr><td>Rest of Asia Pacific</td><td>33,696</td><td>10%</td><td>30,658</td></tr>
      <tr><td>Total net sales</td><td>$416,161</td><td>6%</td><td>$391,035</td></tr>
    </table>
    """
    result = SegmentRevenueExtractor().extract(html, current_year=2025, prior_year=2024)
    assert result.unit == "USD millions"
    assert result.current_total == Decimal("416161")
    assert result.prior_total == Decimal("391035")
    assert result.current_segments["Americas"] == Decimal("178353")
    assert result.prior_segments["Greater China"] == Decimal("66952")


def test_extracts_revenue_rows_grouped_under_segment_names():
    html = """
    <p>Segment results of operations (in millions)</p>
    <table>
      <tr><th></th><th>2025</th><th>2024</th></tr>
      <tr><td>Productivity and Business Processes</td><td></td><td></td></tr>
      <tr><td>Revenue</td><td>$120,810</td><td>$106,820</td></tr>
      <tr><td>Cost of revenue</td><td>22,422</td><td>19,611</td></tr>
      <tr><td>Intelligent Cloud</td><td></td><td></td></tr>
      <tr><td>Revenue</td><td>$106,265</td><td>$87,464</td></tr>
      <tr><td>Cost of revenue</td><td>40,171</td><td>29,611</td></tr>
      <tr><td>More Personal Computing</td><td></td><td></td></tr>
      <tr><td>Revenue</td><td>$54,649</td><td>$50,838</td></tr>
      <tr><td>Total</td><td></td><td></td></tr>
      <tr><td>Revenue</td><td>$281,724</td><td>$245,122</td></tr>
    </table>
    """
    result = SegmentRevenueExtractor().extract(html, current_year=2025, prior_year=2024)
    assert result.current_segments == {
        "Productivity and Business Processes": Decimal("120810"),
        "Intelligent Cloud": Decimal("106265"),
        "More Personal Computing": Decimal("54649"),
    }
    assert result.current_total == Decimal("281724")
    assert result.prior_total == Decimal("245122")


def test_rejects_unreconciled_segment_table():
    html = """
    <p>Reportable segment revenue (in millions)</p>
    <table><tr><th></th><th>2025</th><th>2024</th></tr>
    <tr><td>Segment A</td><td>100</td><td>90</td></tr>
    <tr><td>Segment B</td><td>50</td><td>45</td></tr>
    <tr><td>Total</td><td>200</td><td>135</td></tr></table>
    """
    with pytest.raises(SegmentRevenueError, match="reconciled"):
        SegmentRevenueExtractor().extract(html, current_year=2025, prior_year=2024)


def test_accepts_identical_reconciled_schedules_repeated_in_filing():
    table = """
    <p>Reportable segment revenue (in millions)</p>
    <table><tr><th></th><th>2025</th><th>2024</th></tr>
    <tr><td>Segment A</td><td>100</td><td>90</td></tr>
    <tr><td>Segment B</td><td>50</td><td>45</td></tr>
    <tr><td>Total net sales</td><td>150</td><td>135</td></tr></table>
    """
    result = SegmentRevenueExtractor().extract(
        table + table, current_year=2025, prior_year=2024
    )
    assert result.current_total == Decimal("150")
