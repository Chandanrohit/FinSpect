from __future__ import annotations

from typing import Any

from .client import EdgarClient


class XBRLService:
    """
    Handles SEC XBRL APIs.

    Provides:
    - companyfacts
    - companyconcept
    """

    def __init__(self, client: EdgarClient) -> None:
        self.client = client

    @staticmethod
    def normalize_cik(cik: str | int) -> str:
        """
        Convert CIK to SEC's 10-digit format.
        """

        return str(cik).zfill(10)

    def get_company_facts(
        self,
        cik: str | int,
    ) -> dict[str, Any]:
        """
        Retrieve all available XBRL facts
        for a company.
        """

        cik = self.normalize_cik(cik)

        url = (
            f"{self.client.DATA_BASE_URL}/"
            f"/api/xbrl/companyfacts/"
            f"CIK{cik}.json"
        )

        return self.client.get_json(url)

    def get_company_concept(
        self,
        cik: str | int,
        taxonomy: str,
        concept: str,
    ) -> dict[str, Any]:
        """
        Retrieve one XBRL concept.

        Example:

            taxonomy="us-gaap"
            concept="Revenues"
        """

        cik = self.normalize_cik(cik)

        url = (
            f"{self.client.DATA_BASE_URL}/"
            f"/api/xbrl/companyconcept/"
            f"CIK{cik}/"
            f"{taxonomy}/"
            f"{concept}.json"
        )

        return self.client.get_json(url)