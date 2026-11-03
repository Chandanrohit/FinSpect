"""Extract reportable-segment revenue from a matching SEC filing table."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from .tables import expand_table_grid, parse_sec_amount


class SegmentRevenueError(ValueError):
    """Raised when segment revenue cannot be selected without guessing."""


@dataclass(frozen=True, slots=True)
class SegmentRevenueSchedule:
    current_year: int
    prior_year: int
    current_total: Decimal
    prior_total: Decimal
    current_segments: dict[str, Decimal]
    prior_segments: dict[str, Decimal]
    unit: str
    table_index: int


METRIC_ROW = re.compile(r"^(?:net\s+)?sales:?$|^revenue$", re.I)
TOTAL_ROW = re.compile(r"^(?:total(?:\s+net\s+sales)?|consolidated)$", re.I)
NON_SEGMENT_ROWS = re.compile(
    r"^(?:operating income|cost of revenue|cost of sales|gross margin|"
    r"operating expenses|percentage change|year-over-year.*|net sales mix):?$",
    re.I,
)


def _row_label(row: list[str]) -> str:
    return next((cell.strip() for cell in row if cell.strip()), "")


def _row_values(row: list[str], columns: set[int]) -> set[Decimal]:
    return {
        value
        for column in columns
        if column < len(row)
        if (value := parse_sec_amount(row[column])) is not None
    }


def _unit(table: Tag, text: str) -> str:
    context = " ".join(
        ancestor.get_text(" ", strip=True)
        for ancestor in list(table.parents)[:3]
        if isinstance(ancestor, Tag)
    ).casefold() + " " + text.casefold()
    if re.search(r"\bmillions\b", context):
        return "USD millions"
    if re.search(r"\bthousands\b", context):
        return "USD thousands"
    if re.search(r"\b(?:dollars|usd)\b", context):
        return "USD"
    return "as reported"


class SegmentRevenueExtractor:
    """Read two annual values and their reported total from one disclosure.

    A table qualifies only when its surrounding filing text identifies segment
    data and its segment amounts reconcile to the reported total for both years.
    """

    def extract(
        self, html: str, *, current_year: int, prior_year: int
    ) -> SegmentRevenueSchedule:
        if not html or not html.strip():
            raise ValueError("Filing HTML cannot be empty.")
        if current_year <= prior_year:
            raise ValueError("current_year must be later than prior_year")

        soup = BeautifulSoup(html, "html.parser")
        matches: list[SegmentRevenueSchedule] = []
        for table_index, table in enumerate(soup.find_all("table"), start=1):
            grid = expand_table_grid(table)
            if len(grid) < 3:
                continue
            text = " ".join(" ".join(row) for row in grid)
            nearby_parts = [
                sibling.get_text(" ", strip=True)
                for sibling in list(table.previous_siblings)[:5]
                if isinstance(sibling, Tag)
            ]
            parent = table.parent
            if isinstance(parent, Tag):
                nearby_parts.extend(
                    sibling.get_text(" ", strip=True)
                    for sibling in list(parent.previous_siblings)[:4]
                    if isinstance(sibling, Tag)
                )
            previous_table = next(
                (
                    candidate for candidate in table.find_all_previous("table")
                    if candidate.find_parent("table") is None
                ),
                None,
            )
            preceding_text: list[str] = []
            for node in table.find_all_previous(string=True):
                owner = node.find_parent("table")
                while owner is not None and owner.find_parent("table") is not None:
                    owner = owner.find_parent("table")
                if previous_table is not None and owner is previous_table:
                    break
                preceding_text.append(str(node))
                if sum(map(len, preceding_text)) > 10_000:
                    break
            nearby = " ".join(nearby_parts + preceding_text)
            has_segment_context = bool(re.search(r"segment", nearby + " " + text, re.I))
            if not has_segment_context:
                continue

            header_indexes = [
                index for index, row in enumerate(grid[:12])
                if any(
                    re.search(rf"\b{year}\b", cell)
                    for year in (current_year, prior_year)
                    for cell in row
                )
            ]
            if not header_indexes:
                continue
            header_rows = [grid[index] for index in header_indexes]
            data_start = max(header_indexes) + 1
            if data_start >= len(grid):
                continue
            year_columns: dict[int, set[int]] = {current_year: set(), prior_year: set()}
            for row in header_rows:
                for column, cell in enumerate(row):
                    for year in year_columns:
                        if re.search(rf"\b{year}\b", cell):
                            year_columns[year].add(column)
            if not all(year_columns.values()):
                continue

            segments: dict[str, dict[int, Decimal]] = {}
            totals: dict[int, Decimal] = {}
            active_segment: str | None = None
            metric_mode: str | None = None
            has_revenue_metric = False
            for row in grid[data_start:]:
                label = _row_label(row)
                if not label:
                    continue
                is_revenue_metric = bool(
                    METRIC_ROW.fullmatch(label)
                    or re.fullmatch(r"total\s+net\s+sales", label, re.I)
                )
                if is_revenue_metric:
                    has_revenue_metric = True
                    metric_mode = "revenue"
                current_values = _row_values(row, year_columns[current_year])
                prior_values = _row_values(row, year_columns[prior_year])
                if current_values and prior_values:
                    if len(current_values) != 1 or len(prior_values) != 1:
                        continue
                    current, prior = next(iter(current_values)), next(iter(prior_values))
                    if NON_SEGMENT_ROWS.fullmatch(label):
                        metric_mode = "revenue" if is_revenue_metric else "other"
                        active_segment = None
                        continue
                    if TOTAL_ROW.fullmatch(label) or re.fullmatch(r"total net sales", label, re.I):
                        if metric_mode in {None, "revenue"}:
                            totals = {current_year: current, prior_year: prior}
                    elif METRIC_ROW.fullmatch(label) and active_segment == "__total__":
                        totals = {current_year: current, prior_year: prior}
                    elif METRIC_ROW.fullmatch(label) and active_segment and metric_mode != "other":
                        segments[active_segment] = {current_year: current, prior_year: prior}
                    elif metric_mode != "other":
                        segments[label] = {current_year: current, prior_year: prior}
                    continue

                if not current_values and not prior_values:
                    if TOTAL_ROW.fullmatch(label):
                        active_segment = "__total__"
                    elif is_revenue_metric:
                        metric_mode = "revenue"
                        active_segment = None
                    elif NON_SEGMENT_ROWS.fullmatch(label):
                        metric_mode = "revenue" if is_revenue_metric else "other"
                        active_segment = None
                    elif (
                        not METRIC_ROW.fullmatch(label)
                        and not NON_SEGMENT_ROWS.fullmatch(label)
                        and not re.fullmatch(r"\d{4}", label)
                    ):
                        active_segment = label
            segments.pop("__total__", None)
            if (
                not has_revenue_metric
                or len(segments) < 2
                or set(totals) != {current_year, prior_year}
            ):
                continue
            if (
                sum(item[current_year] for item in segments.values()) != totals[current_year]
                or sum(item[prior_year] for item in segments.values()) != totals[prior_year]
            ):
                continue
            unit_context = nearby + " " + " ".join(
                parent.get_text(" ", strip=True)
                for parent in list(table.parents)[:3]
                if isinstance(parent, Tag)
            )
            unit = _unit(table, text + " " + unit_context)
            schedule = SegmentRevenueSchedule(
                current_year=current_year,
                prior_year=prior_year,
                current_total=totals[current_year],
                prior_total=totals[prior_year],
                current_segments={name: item[current_year] for name, item in segments.items()},
                prior_segments={name: item[prior_year] for name, item in segments.items()},
                unit=unit,
                table_index=table_index,
            )
            matches.append(schedule)
        unique_schedules = {
            (
                match.current_year,
                match.prior_year,
                match.current_total,
                match.prior_total,
                tuple(sorted(match.current_segments.items())),
                tuple(sorted(match.prior_segments.items())),
            ): match
            for match in matches
        }
        if len(unique_schedules) != 1:
            raise SegmentRevenueError(
                f"Expected one reconciled segment-revenue schedule; found {len(unique_schedules)}."
            )
        return next(iter(unique_schedules.values()))
