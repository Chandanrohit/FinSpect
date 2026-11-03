"""Conservative extraction of contractual-obligation schedules in SEC HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from .tables import expand_table_grid, parse_sec_amount


class CommitmentScheduleError(ValueError):
    """Raised when a filing does not contain one unambiguous schedule."""


@dataclass(frozen=True, slots=True)
class CommitmentSchedule:
    total_commitments: Decimal
    next_year_commitments: Decimal
    unit: str
    total_label: str
    near_term_label: str
    table_index: int


def _amount_cell(value: str) -> Decimal | None:
    """Parse an amount while excluding bare years used as table headers."""
    if re.fullmatch(r"(?:19|20)\d{2}", value.strip()):
        return None
    return parse_sec_amount(value)


class CommitmentScheduleExtractor:
    """Find total and next-fiscal-year amounts only in a labeled obligation table.

    This deliberately rejects prose-only disclosures and ambiguous layouts. It
    does not combine different commitment tables, avoiding accidental double
    counting when a filing gives both aggregate and supplemental schedules.
    """

    def extract(self, html: str, *, next_fiscal_year: int) -> CommitmentSchedule:
        if not html or not html.strip():
            raise ValueError("Filing HTML cannot be empty.")
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[CommitmentSchedule] = []
        for table_index, table in enumerate(soup.find_all("table"), start=1):
            grid = expand_table_grid(table)
            if len(grid) < 2:
                continue
            flat = " ".join(" ".join(row) for row in grid).casefold()
            if not re.search(r"contractual obligation|purchase commitment|future commitment|commitments", flat):
                continue
            data_start = next(
                (index for index, row in enumerate(grid)
                 if row and row[0].strip()
                 and (parse_sec_amount(row[0]) is None or re.fullmatch(r"20\d{2}", row[0].strip()))
                 and any(_amount_cell(cell) is not None for cell in row[1:])),
                len(grid),
            )
            header_rows = grid[: min(data_start, 10)]
            if not header_rows or data_start >= len(grid):
                continue
            headers = [
                " ".join(row[col] for row in header_rows if col < len(row)).casefold()
                for col in range(max(map(len, header_rows)))
            ]
            total_cols = [i for i, header in enumerate(headers) if i > 0 and re.search(r"\btotal\b", header)]
            near_cols = [
                i for i, header in enumerate(headers)
                if re.search(r"less than\s*1\s*year|within\s*1\s*year|\b(?:fy\s*)?" + str(next_fiscal_year) + r"\b", header)
            ]
            for row in grid[data_start:]:
                label = next((cell.strip() for cell in row if cell.strip()), "")
                if not re.fullmatch(r"total(?: contractual obligations| commitments| obligations)?\s*:?", label, re.I):
                    continue
                valid_pairs = [
                    (total_col, near_col)
                    for total_col in total_cols for near_col in near_cols
                    if max(total_col, near_col) < len(row)
                    and parse_sec_amount(row[total_col]) is not None
                    and parse_sec_amount(row[near_col]) is not None
                ]
                if len(valid_pairs) == 1:
                    total_col, near_col = valid_pairs[0]
                    total_value = parse_sec_amount(row[total_col])
                    near_value = parse_sec_amount(row[near_col])
                    unit = _unit(table, flat)
                    candidates.append(CommitmentSchedule(total_value, near_value, unit, label, headers[near_col], table_index))
            # Some issuers (including NVIDIA) disclose one fiscal year per
            # row, followed by a total, rather than a one-year column.
            yearly: dict[int, Decimal] = {}
            reported_total: Decimal | None = None
            for row in grid:
                label = next((cell.strip() for cell in row if cell.strip()), "")
                value = next((
                    parse_sec_amount(cell) for cell in row
                    if cell.strip().casefold() != label.casefold()
                    and parse_sec_amount(cell) is not None
                ), None)
                if value is None:
                    continue
                year_match = re.fullmatch(r"(?:fiscal year\s*)?(20\d{2})", label, re.I)
                if year_match:
                    yearly[int(year_match.group(1))] = value
                elif re.fullmatch(r"total", label, re.I):
                    reported_total = value
            if (reported_total is not None and next_fiscal_year in yearly
                    and not (len(total_cols) == 1 and len(near_cols) == 1)):
                unit = _unit(table, flat)
                candidates.append(CommitmentSchedule(reported_total, yearly[next_fiscal_year], unit, "Total", f"FY{next_fiscal_year}", table_index))
        if len(candidates) != 1:
            detail = "No unambiguous total and next-year contractual-obligations schedule was found." if not candidates else "Multiple contractual-obligations schedules matched; refusing to combine or guess."
            raise CommitmentScheduleError(detail)
        return candidates[0]


def _unit(table: Tag, table_text: str) -> str:
    """Read a scale label from the table or its immediate SEC wrapper."""
    context = " ".join(
        ancestor.get_text(" ", strip=True)
        for ancestor in list(table.parents)[:2]
        if isinstance(ancestor, Tag)
    ).casefold() + " " + table_text.casefold()
    if re.search(r"\bmillions\b", context):
        return "USD millions"
    if re.search(r"\bthousands\b", context):
        return "USD thousands"
    if re.search(r"\bin dollars\b|\busd\b", context):
        return "USD"
    return "as reported"
