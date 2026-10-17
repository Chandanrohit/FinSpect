
from __future__ import annotations

from datetime import date
from typing import Any

from .xbrl import XBRLService


class FactRetrievalError(Exception):
    """Raised when a financial fact cannot be selected reliably."""


class FinancialFactRetriever:
    """
    Retrieves a financial fact for an explicitly requested period.

    Selection rules:
    1. Match the requested start and end dates.
    2. Match the requested filing form.
    3. Match the requested unit, if provided.
    4. If duplicate candidates remain, select the most recently filed
       candidate, using accession number as a deterministic tie-breaker.

    For duration facts, start_date is required.
    For instant facts, such as cash at a particular date, start_date=None.
    """

    def __init__(self, xbrl_service: XBRLService) -> None:
        self.xbrl = xbrl_service

    @staticmethod
    def _validate_date(value: str, field_name: str) -> None:
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field_name} must be a valid YYYY-MM-DD date; got {value!r}"
            ) from exc

    def get_fact(
        self,
        *,
        cik: str | int,
        taxonomy: str,
        concept: str,
        start_date: str | None,
        end_date: str,
        form: str,
        unit: str | None = None,
        filed_on_or_before: str | None = None,
        accession_number: str | None = None,
    ) -> dict[str, Any]:
        """
        Return one matching SEC fact with its filing evidence.

        Example:
            get_fact(
                cik="1045810",
                taxonomy="us-gaap",
                concept="RevenueFromContractWithCustomerExcludingAssessedTax",
                start_date="2025-01-27",
                end_date="2026-01-25",
                form="10-K",
                unit="USD",
            )

        The example dates are illustrative, not verified fiscal dates.
        """

        self._validate_date(end_date, "end_date")

        if start_date is not None:
            self._validate_date(start_date, "start_date")
            if start_date > end_date:
                raise ValueError("start_date cannot be after end_date")

        if filed_on_or_before is not None:
            self._validate_date(filed_on_or_before, "filed_on_or_before")

        if not taxonomy.strip() or not concept.strip() or not form.strip():
            raise ValueError("taxonomy, concept, and form must not be empty")

        # Fetch the SEC response using the existing service.
        response = self.xbrl.get_company_concept(
            cik=cik,
            taxonomy=taxonomy,
            concept=concept,
        )

        all_units = response.get("units", {})
        if not all_units:
            raise FactRetrievalError(
                f"No units were returned for concept {concept!r}"
            )

        # Use the requested unit, or require an unambiguous unit.
        if unit is None:
            if len(all_units) != 1:
                raise FactRetrievalError(
                    f"Concept {concept!r} has multiple units: "
                    f"{list(all_units)}. Specify unit explicitly."
                )
            unit = next(iter(all_units))

        if unit not in all_units:
            raise FactRetrievalError(
                f"Unit {unit!r} is unavailable for {concept!r}. "
                f"Available units: {list(all_units)}"
            )

        candidates: list[dict[str, Any]] = []

        for fact in all_units[unit]:
            # Do not mix quarterly, annual, or other forms.
            if fact.get("form") != form:
                continue

            # Exact date matching avoids accidentally selecting a
            # year-to-date fact when a quarter was requested.
            if fact.get("end") != end_date:
                continue

            fact_start = fact.get("start")

            if start_date is None:
                # Instant facts have an end date but no start date.
                if fact_start is not None:
                    continue
            elif fact_start != start_date:
                continue

            filed = fact.get("filed")
            # If a specific SEC filing was requested, require an exact match.
            if (accession_number is not None and fact.get("accn") != accession_number):
                continue

            # Ignore filings later than the optional cutoff.
            if (
                filed_on_or_before is not None
                and filed > filed_on_or_before
            ):
                continue

            candidates.append(fact)

        if not candidates:
            raise FactRetrievalError(
                "No matching fact found for "
                f"{concept!r}, period {start_date or 'instant'} to "
                f"{end_date}, form {form!r}, unit {unit!r}."
            )

        # Prefer the latest filed matching fact. This is an explicit
        # policy, not proof that a fact is always the right business choice.
        candidates.sort(
            key=lambda fact: (
                fact.get("filed", ""),
                fact.get("accn", ""),
            )
        )
        selected = candidates[-1]

        return {
            "cik": str(cik).zfill(10),
            "company": response.get("entityName"),
            "taxonomy": taxonomy,
            "concept": concept,
            "label": response.get("label"),
            "value": selected["val"],
            "unit": unit,
            "start_date": selected.get("start"),
            "end_date": selected["end"],
            "fiscal_year": selected.get("fy"),
            "fiscal_period": selected.get("fp"),
            "form": selected["form"],
            "filing_date": selected["filed"],
            "accession_number": selected.get("accn"),
            "frame": selected.get("frame"),
            "matching_candidate_count": len(candidates),
            "selection_policy": "latest_filed_matching_fact",
        }
