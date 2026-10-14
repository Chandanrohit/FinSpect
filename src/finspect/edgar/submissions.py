from __future__ import annotations

from typing import Any

from .client import EdgarClient


class SubmissionService:
    """
    Handles SEC company submission data.

    Responsibilities:
    - retrieve company submission history
    - filter filings
    - construct official filing URLs
    """

    def __init__(self, client: EdgarClient) -> None:
        self.client = client

    @staticmethod
    def normalize_cik(cik: str | int) -> str:
        """
        Convert a CIK into the SEC's 10-digit format.
        """

        return str(cik).zfill(10)

    def get_company_submissions(
        self,
        cik: str | int,
    ) -> dict[str, Any]:
        """
        Retrieve the company's SEC submission history.
        """

        cik = self.normalize_cik(cik)

        url = (
            f"{self.client.DATA_BASE_URL}/"
            f"submissions/CIK{cik}.json"
        )

        return self.client.get_json(url)

    def get_recent_filings(
        self,
        cik: str | int,
        form: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return recent filings.

        If `form` is provided, only that form is returned.

        Example:
            form="10-K"
            form="10-Q"
        """

        data = self.get_company_submissions(cik)

        recent = data["filings"]["recent"]

        filings: list[dict[str, Any]] = []

        for index, current_form in enumerate(
            recent["form"]
        ):

            if form is not None:
                if current_form != form:
                    continue

            filings.append(
                {
                    "form": current_form,
                    "filing_date": recent[
                        "filingDate"
                    ][index],
                    "report_date": recent[
                        "reportDate"
                    ][index],
                    "accession_number": recent[
                        "accessionNumber"
                    ][index],
                    "primary_document": recent[
                        "primaryDocument"
                    ][index],
                    "file_number": recent[
                        "fileNumber"
                    ][index],
                }
            )

        return filings

    def get_filing_url(
        self,
        cik: str | int,
        accession_number: str,
        primary_document: str,
    ) -> str:
        """
        Construct the official SEC filing URL.
        """

        cik = self.normalize_cik(cik)

        accession_without_dashes = (
            accession_number.replace("-", "")
        )

        numeric_cik = str(int(cik))

        return (
            f"{self.client.SEC_BASE_URL}/"
            f"Archives/edgar/data/"
            f"{numeric_cik}/"
            f"{accession_without_dashes}/"
            f"{primary_document}"
        )

    def get_filing_html(
        self,
        cik: str | int,
        accession_number: str,
        primary_document: str,
    ) -> str:
        """
        Download the official SEC filing HTML.
        """

        url = self.get_filing_url(
            cik=cik,
            accession_number=accession_number,
            primary_document=primary_document,
        )

        return self.client.get_text(url)