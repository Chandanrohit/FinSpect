"""Extract company-reported geographic revenue and classification notes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from .tables import expand_table_grid, parse_sec_amount


class GeographicRevenueError(ValueError):
    """Raised when geographic revenue cannot be identified unambiguously."""


@dataclass(frozen=True, slots=True)
class GeographicRevenueSchedule:
    fiscal_year: int
    total_revenue: Decimal
    geographic_revenue: dict[str, Decimal]
    unit: str
    basis: str
    limitations: tuple[str, ...]
    table_index: int


TOTAL_ROW = re.compile(r"^(?:total(?:\s+(?:net\s+)?sales|\s+revenue)?|consolidated)$", re.I)
GEOGRAPHIC_LABELS = frozenset({
    "u.s.", "u.s", "us", "united states", "united states of america",
    "other countries", "other countries and regions", "international",
    "domestic", "americas", "north america", "south america", "latin america",
    "emea", "europe", "europe, middle east and africa", "middle east and africa",
    "asia", "asia pacific", "asia-pacific", "rest of asia pacific",
    "rest asia pacific", "greater china", "china", "china (including hong kong)",
    "china including hong kong", "hong kong", "taiwan", "japan", "singapore",
    "canada", "united kingdom", "uk", "germany", "france", "australia",
    "india", "brazil", "mexico", "south korea", "korea", "ireland", "israel",
    "other", "rest of world", "rest of the world", "other regions",
})


def _label(row: list[str]) -> str:
    return next((cell.strip() for cell in row if cell.strip()), "")


def _amounts(row: list[str], columns: set[int]) -> set[Decimal]:
    return {
        amount
        for index in columns
        if index < len(row)
        if (amount := parse_sec_amount(row[index])) is not None
    }


def _is_geographic_label(label: str) -> bool:
    normalized = re.sub(r"\s+", " ", label.strip().casefold())
    normalized = re.sub(r"\s*\([^)]*\)\s*", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized in GEOGRAPHIC_LABELS:
        return True
    return bool(re.search(r"\b(?:geographic|geographical)\s+(?:area|region|location)s?\b", normalized))


def _unit(table: Tag, text: str) -> str:
    context = (text + " " + " ".join(
        parent.get_text(" ", strip=True)
        for parent in list(table.parents)[:3]
        if isinstance(parent, Tag)
    )).casefold()
    if re.search(r"\bmillions\b", context):
        return "USD millions"
    if re.search(r"\bthousands\b", context):
        return "USD thousands"
    if re.search(r"\b(?:dollars|usd)\b", context):
        return "USD"
    return "as reported"


def _classification_basis(text: str, limitations: tuple[str, ...] = ()) -> str:
    lower = (text + " " + " ".join(limitations)).casefold()
    if "billing location" in lower or "billing address" in lower:
        return "billing_location"
    if "reportable segments consist" in lower:
        return "management_defined"
    if "location of customers" in lower or "customers were located" in lower:
        return "customer_location"
    return "unspecified"


def _limitations(soup: BeautifulSoup) -> tuple[str, ...]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines()]
    selected: list[str] = []
    for line in lines:
        lower = line.casefold()
        is_definition = any(phrase in lower for phrase in (
            "reportable segments consist of",
            "net sales for geographic segments are generally based",
            "revenue, classified by the major geographic areas",
            "revenue by geographic area is based",
            "revenue by geographic region is designated",
            "revenue classified by the major geographic areas",
            "revenue is classified by customer location",
            "net sales for geographic segments",
        ))
        is_caveat = any(phrase in lower for phrase in (
            "impracticability of determining the geographic source",
            "impracticable to determine",
            "source is impracticable to determine",
            "billing location",
            "shipping location may be different",
            "centralize invoicing",
        ))
        if (is_definition or is_caveat) and line not in selected:
            if lower.startswith("% of fiscal year"):
                continue
            selected.append(line)
    return tuple(selected[:4])


def _bounded_table_context(table: Tag) -> str:
    before: list[str] = []
    for node in table.find_all_previous(string=True):
        before.append(str(node))
        if sum(map(len, before)) > 900:
            break
    after: list[str] = []
    for node in table.find_all_next(string=True):
        if table in node.find_parents("table"):
            continue
        after.append(str(node))
        if sum(map(len, after)) > 400:
            break
    return " ".join([" ".join(reversed(before))[-900:], " ".join(after)[:400]])


class GeographicRevenueExtractor:
    """Select a unique geography-by-revenue table and retain its filing caveats."""

    def extract(self, html: str, *, fiscal_year: int) -> GeographicRevenueSchedule:
        if not html or not html.strip():
            raise ValueError("Filing HTML cannot be empty.")
        if fiscal_year < 1900:
            raise ValueError("fiscal_year must be a valid four-digit year")

        soup = BeautifulSoup(html, "html.parser")
        limitations = _limitations(soup)
        candidates: list[GeographicRevenueSchedule] = []

        for table_index, table in enumerate(soup.find_all("table"), start=1):
            grid = expand_table_grid(table)
            if len(grid) < 3:
                continue
            table_text = re.sub(r"\s+", " ", table.get_text(" ", strip=True))
            context = _bounded_table_context(table)
            full_text = context + " " + table_text
            if re.search(r"long-lived assets|revenue by end market|revenue by product|product and service offerings", table_text, re.I):
                continue
            # Point-in-time geographic asset schedules can use the same area
            # labels and a reconciled total. Exclude them by their as-of date;
            # otherwise require duration evidence or nearby explicit revenue
            # classification text.
            revenue_signal = re.search(
                r"\byear ended\b|\b(?:total\s+)?(?:net\s+)?sales\b|\brevenue\b",
                table_text,
                re.I,
            )
            point_in_time = re.search(
                r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}\b|\bas of\b",
                table_text,
                re.I,
            )
            if point_in_time and not re.search(r"\byear ended\b", table_text, re.I):
                continue
            if not revenue_signal and not re.search(r"geograph|geographical", context, re.I):
                continue

            year_rows = [
                row for row in grid[:12]
                if any(re.search(rf"\b{fiscal_year}\b", cell) for cell in row)
            ]
            year_columns = {
                index
                for row in year_rows
                for index, cell in enumerate(row)
                if re.search(rf"\b{fiscal_year}\b", cell)
            }
            if not year_columns:
                continue

            total: Decimal | None = None
            exposures: dict[str, Decimal] = {}
            for row in grid[max((grid.index(item) for item in year_rows), default=-1) + 1:]:
                label = _label(row)
                if not label:
                    continue
                values = _amounts(row, year_columns)
                if len(values) != 1:
                    continue
                value = next(iter(values))
                if TOTAL_ROW.fullmatch(label):
                    total = value
                elif re.search(r"\b(?:revenue|net sales|net revenue)\b", label, re.I):
                    continue
                elif not re.search(r"\b(?:change|growth|percentage|percent|mix)\b", label, re.I):
                    normalized_label = re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()
                    if _is_geographic_label(normalized_label):
                        exposures[normalized_label] = value

            if total is None or len(exposures) < 2:
                continue
            if sum(exposures.values()) != total:
                continue

            candidates.append(GeographicRevenueSchedule(
                fiscal_year=fiscal_year,
                total_revenue=total,
                geographic_revenue=exposures,
                unit=_unit(table, context + " " + table_text),
                basis=_classification_basis(full_text, limitations),
                limitations=limitations,
                table_index=table_index,
            ))

        unique = {
            (
                item.fiscal_year,
                item.total_revenue,
                tuple(sorted(item.geographic_revenue.items())),
            ): item
            for item in candidates
        }
        if len(unique) > 1:
            most_detailed = max(len(item.geographic_revenue) for item in unique.values())
            unique = {
                key: item for key, item in unique.items()
                if len(item.geographic_revenue) == most_detailed
            }
        if len(unique) != 1:
            candidate_tables = sorted({item.table_index for item in candidates})
            raise GeographicRevenueError(
                f"Expected one most-detailed reconciled geographic-revenue schedule; found {len(unique)} "
                f"across table(s) {candidate_tables}."
            )
        result = next(iter(unique.values()))
        if not result.limitations:
            raise GeographicRevenueError(
                "The filing did not provide a geographic classification limitation or distinction."
            )
        return result
