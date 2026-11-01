
import pytest

from finspect.edgar.company_resolver import (
    CompanyResolutionError,
    SECCompanyResolver,
)


class FakeSECClient:
    def get_json(self, url):
        return {
            "0": {
                "cik_str": 789019,
                "title": "Microsoft Corporation",
                "ticker": "MSFT",
            },
            "1": {
                "cik_str": 1018724,
                "title": "Amazon.com, Inc.",
                "ticker": "AMZN",
            },
        }


def test_resolves_company_by_ticker():
    resolver = SECCompanyResolver(FakeSECClient())

    result = resolver.resolve(ticker="MSFT")

    assert result["name"] == "Microsoft Corporation"
    assert result["ticker"] == "MSFT"
    assert result["cik"] == "0000789019"


def test_resolves_exact_company_name():
    resolver = SECCompanyResolver(FakeSECClient())

    result = resolver.resolve(name="Amazon.com, Inc.")

    assert result["ticker"] == "AMZN"


def test_unknown_company_raises_clear_error():
    resolver = SECCompanyResolver(FakeSECClient())

    with pytest.raises(CompanyResolutionError, match="No SEC company match"):
        resolver.resolve(name="Unknown Example Company")


def test_missing_company_identifier_raises():
    resolver = SECCompanyResolver(FakeSECClient())

    with pytest.raises(CompanyResolutionError, match="Provide a company"):
        resolver.resolve()


def test_cik_conflicting_with_ticker_is_rejected():
    resolver = SECCompanyResolver(FakeSECClient())

    with pytest.raises(CompanyResolutionError, match="ticker and CIK"):
        resolver.resolve(cik="789019", ticker="AMZN")


def test_cik_conflicting_with_exact_company_name_is_rejected():
    resolver = SECCompanyResolver(FakeSECClient())

    with pytest.raises(CompanyResolutionError, match="name and CIK"):
        resolver.resolve(cik="789019", name="Amazon.com, Inc.")


def test_corporate_suffix_variants_normalize_equally():
    resolver = SECCompanyResolver(FakeSECClient())

    result = resolver.resolve(cik="1018724", name="Amazon.com, Inc.")

    assert result["ticker"] == "AMZN"
