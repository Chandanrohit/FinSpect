
import pytest

from finspect.period_resolver import find_annual_revenue_fact, resolve_annual_period, AnnualPeriod


@pytest.fixture
def nvidia_company_facts():
    """Representative SEC company-facts response for NVIDIA."""
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-30",
                                "end": "2024-01-28",
                                "form": "10-K",
                                "fy": 2024,
                                "fp": "FY",
                                "filed": "2024-02-21",
                                "val": 60_922_000_000,
                                "accn": "0001045810-24-000029",
                            },
                            {
                                # Same comparative period in a later filing.
                                "start": "2023-01-30",
                                "end": "2024-01-28",
                                "form": "10-K",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2025-02-26",
                                "val": 60_922_000_000,
                                "accn": "0001045810-25-000023",
                            },
                            {
                                "start": "2024-01-29",
                                "end": "2025-01-26",
                                "form": "10-K",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2025-02-26",
                                "val": 130_497_000_000,
                                "accn": "0001045810-25-000023",
                            },
                        ]
                    }
                }
            }
        }
    }


def test_finds_fy2024_revenue(nvidia_company_facts):
    fact = find_annual_revenue_fact(nvidia_company_facts, 2024)

    assert fact["concept"] == "Revenues"
    assert fact["start"] == "2023-01-30"
    assert fact["end"] == "2024-01-28"
    assert fact["val"] == 60_922_000_000


def test_prefers_original_filing_over_comparative(
    nvidia_company_facts,
):
    fact = find_annual_revenue_fact(nvidia_company_facts, 2024)

    assert fact["filed"] == "2024-02-21"
    assert fact["accn"] == "0001045810-24-000029"


def test_finds_fy2025_revenue(nvidia_company_facts):
    fact = find_annual_revenue_fact(nvidia_company_facts, 2025)

    assert fact["end"] == "2025-01-26"
    assert fact["val"] == 130_497_000_000


def test_ignores_quarterly_revenue(nvidia_company_facts):
    quarterly_fact = {
        "start": "2023-10-30",
        "end": "2024-01-28",
        "form": "10-K",
        "filed": "2024-02-21",
        "val": 10_000,
    }

    nvidia_company_facts["facts"]["us-gaap"]["Revenues"][
        "units"
    ]["USD"].append(quarterly_fact)

    fact = find_annual_revenue_fact(nvidia_company_facts, 2024)

    assert fact["val"] == 60_922_000_000


def test_raises_for_missing_fiscal_year(nvidia_company_facts):
    with pytest.raises(ValueError, match="No annual revenue fact"):
        find_annual_revenue_fact(nvidia_company_facts, 2022)


def test_ignores_facts_without_a_start_date(nvidia_company_facts):
    instant_fact = {
        "start": None,
        "end": "2024-01-28",
        "form": "10-K",
        "filed": "2024-02-21",
        "val": 999,
    }

    nvidia_company_facts["facts"]["us-gaap"]["Revenues"][
        "units"
    ]["USD"].append(instant_fact)

    fact = find_annual_revenue_fact(nvidia_company_facts, 2024)

    assert fact["val"] == 60_922_000_000


def test_resolver_preserves_original_filing_metadata(
    nvidia_company_facts,
):
    class FakeXBRLService:
        def get_company_facts(self, cik):
            return nvidia_company_facts

    period = resolve_annual_period(
        "0001045810",
        2024,
        xbrl_service=FakeXBRLService(),
    )

    assert period.start_date == "2023-01-30"
    assert period.end_date == "2024-01-28"
    assert period.concept == "Revenues"
    assert period.filing_date == "2024-02-21"
    assert period.accession_number == "0001045810-24-000029"
