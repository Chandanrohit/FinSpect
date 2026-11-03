"""Extract reconciled operating-expense categories from an SEC filing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from bs4 import BeautifulSoup, Tag

from .tables import expand_table_grid, parse_sec_amount


class OperatingExpenseError(ValueError):
    """Raised when a filing has no unique reconciled expense schedule."""


@dataclass(frozen=True, slots=True)
class OperatingExpenseSchedule:
    current_year: int
    prior_year: int
    current_total: Decimal
    prior_total: Decimal
    current_categories: dict[str, Decimal]
    prior_categories: dict[str, Decimal]
    unit: str
    total_method: str
    table_index: int
    current_gross_margin: Decimal | None = None
    prior_gross_margin: Decimal | None = None
    current_operating_income: Decimal | None = None
    prior_operating_income: Decimal | None = None


TOTAL_EXPENSES = re.compile(r"^total\s+operating\s+expenses:?$", re.I)
GROSS_MARGIN = re.compile(r"^gross\s+margin:?$", re.I)
OPERATING_INCOME = re.compile(r"^operating\s+income(?:\s+loss)?:?$", re.I)
SECTION_HEADING = re.compile(r"^operating\s+expenses:?$", re.I)


def _label(row: list[str]) -> str:
    return next((cell.strip() for cell in row if cell.strip()), "")


def _values(row: list[str], columns: set[int]) -> set[Decimal]:
    return {
        amount
        for index in columns
        if index < len(row)
        if (amount := parse_sec_amount(row[index])) is not None
    }


def _unit(table: Tag, context: str) -> str:
    text = (context + " " + " ".join(
        ancestor.get_text(" ", strip=True)
        for ancestor in list(table.parents)[:3]
        if isinstance(ancestor, Tag)
    )).casefold()
    if re.search(r"\bmillions\b", text):
        return "USD millions"
    if re.search(r"\bthousands\b", text):
        return "USD thousands"
    if re.search(r"\b(?:dollars|usd)\b", text):
        return "USD"
    return "as reported"


class OperatingExpenseExtractor:
    """Read annual categories and totals from one comparable SEC disclosure."""

    def extract(
        self, html: str, *, current_year: int, prior_year: int
    ) -> OperatingExpenseSchedule:
        if not html or not html.strip():
            raise ValueError("Filing HTML cannot be empty.")
        if current_year <= prior_year:
            raise ValueError("current_year must be later than prior_year")

        soup = BeautifulSoup(html, "html.parser")
        candidates: list[OperatingExpenseSchedule] = []
        for table_index, table in enumerate(soup.find_all("table"), start=1):
            grid = expand_table_grid(table)
            if len(grid) < 3:
                continue
            text = " ".join(" ".join(row) for row in grid)
            if not (
                re.search(r"operating\s+expenses", text, re.I)
                or (
                    re.search(r"\bgross\s+margin\b", text, re.I)
                    and re.search(r"\boperating\s+income\b", text, re.I)
                )
            ):
                continue

            header_indexes = [
                index for index, row in enumerate(grid[:12])
                if any(
                    re.search(rf"\b{year}\b", cell)
                    for year in (current_year, prior_year)
                    for cell in row
                )
            ]
            year_rows = [grid[index] for index in header_indexes]
            year_columns: dict[int, set[int]] = {current_year: set(), prior_year: set()}
            for row in year_rows:
                for index, cell in enumerate(row):
                    for year in year_columns:
                        if re.search(rf"\b{year}\b", cell):
                            year_columns[year].add(index)
            if not all(year_columns.values()):
                continue

            categories: dict[str, dict[int, Decimal]] = {}
            explicit_totals: dict[int, Decimal] = {}
            gross_margin: dict[int, Decimal] = {}
            operating_income: dict[int, Decimal] = {}
            in_expenses = False
            for row in grid[(max(header_indexes) + 1):]:
                label = _label(row)
                if not label:
                    continue
                current = _values(row, year_columns[current_year])
                prior = _values(row, year_columns[prior_year])

                if SECTION_HEADING.fullmatch(label):
                    in_expenses = True
                    continue
                if not current or not prior or len(current) != 1 or len(prior) != 1:
                    if GROSS_MARGIN.fullmatch(label):
                        in_expenses = True
                    continue
                current_value = next(iter(current))
                prior_value = next(iter(prior))
                if GROSS_MARGIN.fullmatch(label):
                    gross_margin = {current_year: current_value, prior_year: prior_value}
                    in_expenses = True
                elif TOTAL_EXPENSES.fullmatch(label):
                    explicit_totals = {current_year: current_value, prior_year: prior_value}
                    break
                elif OPERATING_INCOME.fullmatch(label):
                    operating_income = {current_year: current_value, prior_year: prior_value}
                    in_expenses = False
                    break
                elif in_expenses:
                    categories[label.rstrip(":")] = {
                        current_year: current_value,
                        prior_year: prior_value,
                    }

            if len(categories) < 2:
                continue
            total_method = "reported total operating expenses"
            totals = explicit_totals
            if (
                not totals
                and set(gross_margin) == {current_year, prior_year}
                and set(operating_income) == {current_year, prior_year}
            ):
                totals = {
                    year: gross_margin[year] - operating_income[year]
                    for year in (current_year, prior_year)
                }
                total_method = "gross margin minus operating income"
            if set(totals) != {current_year, prior_year}:
                continue
            if any(
                sum(values[year] for values in categories.values()) != totals[year]
                for year in (current_year, prior_year)
            ):
                continue

            candidates.append(OperatingExpenseSchedule(
                current_year=current_year,
                prior_year=prior_year,
                current_total=totals[current_year],
                prior_total=totals[prior_year],
                current_categories={name: item[current_year] for name, item in categories.items()},
                prior_categories={name: item[prior_year] for name, item in categories.items()},
                unit=_unit(table, text),
                total_method=total_method,
                table_index=table_index,
                current_gross_margin=gross_margin.get(current_year),
                prior_gross_margin=gross_margin.get(prior_year),
                current_operating_income=operating_income.get(current_year),
                prior_operating_income=operating_income.get(prior_year),
            ))

        unique = {
            (
                item.current_year,
                item.prior_year,
                item.current_total,
                item.prior_total,
                tuple(sorted(item.current_categories.items())),
                tuple(sorted(item.prior_categories.items())),
            ): item
            for item in candidates
        }
        if len(unique) != 1:
            raise OperatingExpenseError(
                f"Expected one reconciled operating-expense schedule; found {len(unique)}."
            )
        return next(iter(unique.values()))
