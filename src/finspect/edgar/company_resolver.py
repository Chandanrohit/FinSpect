
from __future__ import annotations

import re
from typing import Any


class CompanyResolutionError(ValueError):
    """Raised when a company cannot be resolved unambiguously."""


def normalize_company_text(value: str) -> str:
    """Normalize company names and tickers for comparison."""
    value = value.casefold().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\b(corp|corporation)\b", "corporation", value)
    value = re.sub(r"\b(inc|incorporated)\b", "incorporated", value)
    value = re.sub(r"\b(co|company)\b", "company", value)
    value = re.sub(r"\b(ltd|limited)\b", "limited", value)
    return " ".join(value.split())


class SECCompanyResolver:
    """Resolve company names and tickers using SEC company metadata."""

    METADATA_URL = "https://www.sec.gov/files/company_tickers.json"

    def __init__(self, client: Any) -> None:
        self.client = client
        self._companies: list[dict[str, str]] | None = None

    def _load_companies(self) -> list[dict[str, str]]:
        if self._companies is None:
            payload = self.client.get_json(self.METADATA_URL)

            # SEC metadata is normally a dictionary indexed by row number.
            rows = payload.values() if isinstance(payload, dict) else payload

            companies = []
            for row in rows:
                if not isinstance(row, dict):
                    continue

                cik = str(row.get("cik_str", "")).strip()
                name = str(row.get("title", "")).strip()
                ticker = str(row.get("ticker", "")).strip().upper()

                if cik.isdigit() and name and ticker:
                    companies.append({
                        "cik": cik.zfill(10),
                        "name": name,
                        "ticker": ticker,
                    })

            self._companies = companies

        return self._companies

    @staticmethod
    def _match_company_name(
        name: str,
        companies: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        normalized = normalize_company_text(name)
        exact = [
            company for company in companies
            if normalize_company_text(company["name"]) == normalized
        ]
        if exact:
            return exact
        # SEC metadata uses legal entity names; accept a unique leading name
        # such as "Microsoft" for "Microsoft Corporation", but fail closed
        # when that short name could refer to multiple registrants.
        return [
            company for company in companies
            if normalize_company_text(company["name"]).startswith(normalized + " ")
        ]

    def resolve(
        self,
        *,
        name: str | None = None,
        ticker: str | None = None,
        cik: str | None = None,
    ) -> dict[str, str]:
        """Resolve an explicit CIK, ticker, or exact normalized company name."""

        companies = self._load_companies()

        if cik:
            normalized_cik = cik.strip().zfill(10)
            matches = [
                company for company in companies
                if company["cik"] == normalized_cik
            ]

            # A planner may return a plausible but incorrect CIK. When it
            # also supplied a ticker or an exact SEC company name, require
            # those identifiers to agree with the CIK lookup.
            if len(matches) == 1:
                resolved = matches[0]
                if ticker and ticker.strip().upper() != resolved["ticker"]:
                    raise CompanyResolutionError(
                        "The supplied ticker and CIK identify different SEC companies."
                    )

                if name and name.strip():
                    exact_name_matches = self._match_company_name(name, companies)
                    if (
                        len(exact_name_matches) == 1
                        and exact_name_matches[0]["cik"] != resolved["cik"]
                    ):
                        raise CompanyResolutionError(
                            "The supplied company name and CIK identify different SEC companies."
                        )
        elif ticker and ticker.strip():
            requested_ticker = ticker.strip().upper()
            matches = [
                company for company in companies
                if company["ticker"] == requested_ticker
            ]
        elif name and name.strip():
            matches = self._match_company_name(name, companies)
        else:
            raise CompanyResolutionError(
                "Provide a company name, ticker, or CIK."
            )

        # Multiple listed share classes can map to the same SEC registrant.
        if len(matches) > 1 and len({company["cik"] for company in matches}) == 1:
            matches = [min(matches, key=lambda company: company["ticker"])]

        if len(matches) == 0:
            raise CompanyResolutionError(
                f"No SEC company match found for "
                f"name={name!r}, ticker={ticker!r}, cik={cik!r}."
            )

        if len(matches) > 1:
            raise CompanyResolutionError(
                "Company lookup is ambiguous. Please provide the exact "
                "ticker or CIK."
            )

        return matches[0]
