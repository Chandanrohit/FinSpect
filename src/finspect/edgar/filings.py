
from __future__ import annotations

from typing import Any

from .submissions import SubmissionService


class FilingRetrievalError(Exception):
    """Raised when a filing cannot be located or retrieved."""


class FilingRetriever:
    def __init__(self, submissions: SubmissionService) -> None:
        self.submissions = submissions

    def get_latest_filing(
        self,
        *,
        cik: str | int,
        form: str = "10-K",
    ) -> dict[str, Any]:
        """Return the latest filing metadata and its HTML content."""

        filings = self.submissions.get_recent_filings(
            cik=cik,
            form=form,
        )

        if not filings:
            raise FilingRetrievalError(
                f"No recent {form} filing found for CIK {cik}."
            )

        # SEC submission history is normally newest-first, but sort
        # explicitly so the selection policy is clear.
        filings.sort(
            key=lambda filing: filing["filing_date"],
            reverse=True,
        )

        selected = filings[0]

        html = self.submissions.get_filing_html(
            cik=cik,
            accession_number=selected["accession_number"],
            primary_document=selected["primary_document"],
        )

        return {
            **selected,
            "cik": str(cik).zfill(10),
            "html": html,
        }
