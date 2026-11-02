import pytest

from finspect.edgar.equity_statement import (
    EquityStatementError,
    EquityStatementExtractor,
)
from finspect.calculator import largest_component_contribution


def make_statement(*, title="Consolidated Statements of Shareholders’ Equity"):
    return f"""
    <div><p>{title}</p>
    <table>
      <tr><th>(In millions, except per share amounts)</th><th>2025</th><th>2024</th></tr>
      <tr><td>Net income</td><td>112,010</td><td>93,736</td></tr>
      <tr><td>Common stock issued</td><td>1,498</td><td>1,423</td></tr>
      <tr><td>Dividends declared</td><td>(15,413)</td><td>(15,218)</td></tr>
      <tr><td>Common stock repurchased</td><td>(90,052)</td><td>(95,846)</td></tr>
      <tr><td>Other comprehensive income</td><td>1,601</td><td>4,280</td></tr>
      <tr><td>Total shareholders’ equity, ending balances</td><td>73,733</td><td>56,950</td></tr>
    </table></div>
    """


def test_extracts_selected_fiscal_year_rows_with_scale_and_sign():
    statement = EquityStatementExtractor().extract(
        make_statement(), fiscal_year=2025, period_end="2025-09-27"
    )

    assert statement.fiscal_year == 2025
    assert statement.period_end == "2025-09-27"
    assert statement.unit == "USD millions"
    assert statement.ending_equity == 73733_000_000
    assert statement.components["Net income"] == 112010_000_000
    assert statement.components["Common stock repurchased"] == -90052_000_000
    assert statement.components["Dividends declared"] == -15413_000_000


def test_uses_expanded_header_colspans_to_select_year_columns():
    html = """
    <table>
      <tr><th rowspan="2">(In millions)</th><th colspan="2">Year Ended</th></tr>
      <tr><th>2025</th><th>2024</th></tr>
      <tr><td>Net income</td><td>72,880</td><td>29,760</td></tr>
      <tr><td>Repurchases</td><td>(34,015)</td><td>(9,746)</td></tr>
      <tr><td>Dividends</td><td>(834)</td><td>(395)</td></tr>
      <tr><td>Balances as of Jan 26, 2025</td><td>79,327</td><td>42,978</td></tr>
    </table>
    """
    statement = EquityStatementExtractor().extract(
        html, fiscal_year=2025, period_end="2025-01-26"
    )

    assert statement.ending_equity == 79327_000_000
    assert statement.components["Net income"] == 72880_000_000
    assert statement.components["Repurchases"] == -34015_000_000


def test_extracts_activity_rows_between_exact_balance_dates():
    html = """
    <p>(In millions)</p>
    <table>
      <tr><td>Balances as of Jan 28, 2024</td><td>42,978</td></tr>
      <tr><td>Net income</td><td>72,880</td></tr>
      <tr><td>Other comprehensive income</td><td>1</td></tr>
      <tr><td>Shares repurchased</td><td>(34,015)</td></tr>
      <tr><td>Cash dividends declared</td><td>(834)</td></tr>
      <tr><td>Balances as of Jan 26, 2025</td><td>79,327</td></tr>
    </table>
    """
    statement = EquityStatementExtractor().extract(
        html, fiscal_year=2025, period_end="2025-01-26"
    )

    assert statement.ending_equity == 79327_000_000
    assert statement.components == {
        "Net income": 72880_000_000,
        "Other comprehensive income": 1_000_000,
        "Shares repurchased": -34015_000_000,
        "Cash dividends declared": -834_000_000,
    }


def test_extracts_multi_column_component_rows_and_split_accounting_parentheses():
    html = """
    <p>STOCKHOLDERS’ EQUITY STATEMENTS</p>
    <p>(In millions)</p>
    <table>
      <tr><td>Year Ended June 30,</td><td>2025</td><td>2024</td></tr>
      <tr><td>Common stock issued</td><td>2,056</td><td>2,002</td></tr>
      <tr><td>Common stock repurchased</td><td>(5,856</td><td>)</td><td>(5,712)</td></tr>
      <tr><td>Net income</td><td>101,832</td><td>88,136</td></tr>
      <tr><td>Common stock cash dividends</td><td>(24,677)</td><td>(22,293)</td></tr>
      <tr><td>Total stockholders’ equity</td><td>343,479</td><td>268,477</td></tr>
    </table>
    """
    statement = EquityStatementExtractor().extract(
        html, fiscal_year=2025, period_end="2025-06-30"
    )

    assert statement.ending_equity == 343479_000_000
    assert statement.components["Common stock repurchased"] == -5856_000_000
    assert statement.components["Net income"] == 101832_000_000


@pytest.mark.parametrize(
    ("html", "fiscal_year", "period_end", "ending_equity", "largest_label", "largest_amount"),
    [
        (
            """<p>(In millions)</p><table>
            <tr><td>Balances as of Jan 28, 2024</td><td>42,978</td></tr>
            <tr><td>Net income</td><td>72,880</td></tr>
            <tr><td>Other comprehensive income</td><td>1</td></tr>
            <tr><td>Issuance of common stock from stock plans</td><td>490</td></tr>
            <tr><td>Tax withholding related to vesting of restricted stock units</td><td>(6,930)</td></tr>
            <tr><td>Shares repurchased</td><td>(34,015)</td></tr>
            <tr><td>Cash dividends declared and paid</td><td>(834)</td></tr>
            <tr><td>Stock-based compensation</td><td>4,757</td></tr>
            <tr><td>Balances as of Jan 26, 2025</td><td>79,327</td></tr>
            </table>""",
            2025, "2025-01-26", 79_327_000_000, "Net income", 72_880_000_000,
        ),
        (
            """<p>(In millions)</p><table>
            <tr><td>Balances as of Jan 29, 2023</td><td>22,101</td></tr>
            <tr><td>Net income</td><td>29,760</td></tr>
            <tr><td>Other comprehensive income</td><td>70</td></tr>
            <tr><td>Issuance of common stock from stock plans</td><td>403</td></tr>
            <tr><td>Tax withholding related to vesting of restricted stock units</td><td>(2,783)</td></tr>
            <tr><td>Shares repurchased</td><td>(9,746)</td></tr>
            <tr><td>Cash dividends declared and paid</td><td>(395)</td></tr>
            <tr><td>Stock-based compensation</td><td>3,568</td></tr>
            <tr><td>Balances as of Jan 28, 2024</td><td>42,978</td></tr>
            </table>""",
            2024, "2024-01-28", 42_978_000_000, "Net income", 29_760_000_000,
        ),
        (
            """<p>STOCKHOLDERS’ EQUITY STATEMENTS</p><p>(In millions)</p><table>
            <tr><td>Year Ended June 30,</td><td>2025</td><td>2024</td></tr>
            <tr><td>Balance, beginning of period</td><td>100,923</td><td>93,718</td></tr>
            <tr><td>Common stock issued</td><td>2,056</td><td>2,002</td></tr>
            <tr><td>Common stock repurchased</td><td>(5,856)</td><td>(5,712)</td></tr>
            <tr><td>Stock-based compensation expense</td><td>11,974</td><td>10,734</td></tr>
            <tr><td>Net income</td><td>101,832</td><td>88,136</td></tr>
            <tr><td>Common stock cash dividends</td><td>(24,677)</td><td>(22,293)</td></tr>
            <tr><td>Common stock repurchased</td><td>(12,568)</td><td>(11,547)</td></tr>
            <tr><td>Other comprehensive income (loss)</td><td>2,243</td><td>753</td></tr>
            <tr><td>Total stockholders’ equity</td><td>343,479</td><td>268,477</td></tr>
            </table>""",
            2025, "2025-06-30", 343_479_000_000, "Net income", 101_832_000_000,
        ),
        (
            """<p>STOCKHOLDERS’ EQUITY STATEMENTS</p><p>(In millions)</p><table>
            <tr><td>Year Ended June 30,</td><td>2024</td><td>2023</td></tr>
            <tr><td>Balance, beginning of period</td><td>93,718</td><td>86,939</td></tr>
            <tr><td>Common stock issued</td><td>2,002</td><td>1,866</td></tr>
            <tr><td>Common stock repurchased</td><td>(5,712)</td><td>(4,696)</td></tr>
            <tr><td>Stock-based compensation expense</td><td>10,734</td><td>9,611</td></tr>
            <tr><td>Net income</td><td>88,136</td><td>72,361</td></tr>
            <tr><td>Common stock cash dividends</td><td>(22,293)</td><td>(20,226)</td></tr>
            <tr><td>Common stock repurchased</td><td>(11,547)</td><td>(17,568)</td></tr>
            <tr><td>Other comprehensive income (loss)</td><td>753</td><td>(1,665)</td></tr>
            <tr><td>Total stockholders’ equity</td><td>268,477</td><td>206,223</td></tr>
            </table>""",
            2024, "2024-06-30", 268_477_000_000, "Net income", 88_136_000_000,
        ),
        (
            """<p>CONSOLIDATED STATEMENTS OF SHAREHOLDERS’ EQUITY</p>
            <p>(In millions, except per-share amounts)</p><table>
            <tr><td>Years ended</td><td>September 27, 2025</td><td>September 28, 2024</td></tr>
            <tr><td>Total shareholders’ equity, beginning balances</td><td>56,950</td><td>62,146</td></tr>
            <tr><td>Common stock issued</td><td>1,498</td><td>1,423</td></tr>
            <tr><td>Share-based compensation</td><td>13,246</td><td>12,034</td></tr>
            <tr><td>Net income</td><td>112,010</td><td>93,736</td></tr>
            <tr><td>Dividends and dividend equivalents declared</td><td>(15,413)</td><td>(15,218)</td></tr>
            <tr><td>Common stock repurchased</td><td>(90,052)</td><td>(95,846)</td></tr>
            <tr><td>Other comprehensive income/(loss)</td><td>1,601</td><td>4,280</td></tr>
            <tr><td>Total shareholders’ equity, ending balances</td><td>73,733</td><td>56,950</td></tr>
            </table>""",
            2025, "2025-09-27", 73_733_000_000, "Net income", 112_010_000_000,
        ),
        (
            """<p>CONSOLIDATED STATEMENTS OF SHAREHOLDERS’ EQUITY</p>
            <p>(In millions, except per-share amounts)</p><table>
            <tr><td>Years ended</td><td>September 28, 2024</td><td>September 30, 2023</td></tr>
            <tr><td>Total shareholders’ equity, beginning balances</td><td>62,146</td><td>50,672</td></tr>
            <tr><td>Common stock issued</td><td>1,423</td><td>1,346</td></tr>
            <tr><td>Share-based compensation</td><td>12,034</td><td>11,138</td></tr>
            <tr><td>Net income</td><td>93,736</td><td>96,995</td></tr>
            <tr><td>Dividends and dividend equivalents declared</td><td>(15,218)</td><td>(14,996)</td></tr>
            <tr><td>Common stock repurchased</td><td>(95,846)</td><td>(77,046)</td></tr>
            <tr><td>Other comprehensive income/(loss)</td><td>4,280</td><td>(343)</td></tr>
            <tr><td>Total shareholders’ equity, ending balances</td><td>56,950</td><td>62,146</td></tr>
            </table>""",
            2024, "2024-09-28", 56_950_000_000, "Common stock repurchased", -95_846_000_000,
        ),
    ],
    ids=[
        "nvidia-date-anchored-fy2025", "nvidia-date-anchored-fy2024",
        "microsoft-grouped-equity-fy2025", "microsoft-grouped-equity-fy2024",
        "apple-dated-columns-fy2025", "apple-dated-columns-fy2024",
    ],
)
def test_reference_issuer_statement_shapes_select_expected_largest_row(
    html, fiscal_year, period_end, ending_equity, largest_label, largest_amount
):
    statement = EquityStatementExtractor().extract(
        html, fiscal_year=fiscal_year, period_end=period_end
    )
    selected_label, result = largest_component_contribution(
        statement.components, statement.ending_equity
    )

    assert statement.ending_equity == ending_equity
    assert selected_label == largest_label
    assert result.inputs[selected_label] == largest_amount


def test_fails_closed_when_no_annual_equity_table_is_present():
    with pytest.raises(EquityStatementError, match="No complete"):
        EquityStatementExtractor().extract(
            "<table><tr><td>Net income</td><td>100</td></tr></table>",
            fiscal_year=2025,
            period_end="2025-12-31",
        )


def test_fails_closed_when_multiple_complete_equity_tables_are_present():
    with pytest.raises(EquityStatementError, match="refusing to choose ambiguously"):
        EquityStatementExtractor().extract(
            make_statement() + make_statement(title="Statement of stockholders’ equity"),
            fiscal_year=2025,
            period_end="2025-09-27",
        )
