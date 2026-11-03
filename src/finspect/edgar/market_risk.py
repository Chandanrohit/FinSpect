"""Extract annual interest-rate sensitivity of an issuer's investment portfolio."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from bs4 import BeautifulSoup
from bs4.element import Tag

from .parser import FilingParser
from .tables import expand_table_grid, parse_sec_amount


class MarketRiskError(ValueError):
    """Raised when the filing does not disclose one clear sensitivity."""


@dataclass(frozen=True, slots=True)
class MarketRiskSensitivity:
    fiscal_year: int
    scenario: str
    impact: str
    sensitivity_amount: Decimal
    unit: str
    disclosure: str
    table_index: int | None


def _row_label(row: list[str]) -> str:
    return next((cell.strip() for cell in row if cell.strip()), "")


def _parse_narrative(section: str, fiscal_year: int) -> list[MarketRiskSensitivity]:
    clean = re.sub(r"\s+", " ", section)
    match = re.search(
        rf"parallel shifts? in the yield curve of (?P<scenario>plus or minus \d+(?:\.\d+)?%)"
        rf" would result in a change in fair value for these investments of\s*\$\s*"
        rf"(?P<amount>[\d,]+)\s+million",
        clean,
        re.I,
    )
    if not match:
        return []
    if not re.search(rf"fiscal year {fiscal_year}\b", clean, re.I):
        return []
    excerpt = match.group(0)
    return [MarketRiskSensitivity(
        fiscal_year=fiscal_year,
        scenario=f"Parallel yield-curve shift {match.group('scenario')}",
        impact="fair value of investment portfolio",
        sensitivity_amount=Decimal(match.group("amount").replace(",", "")),
        unit="USD millions",
        disclosure=excerpt,
        table_index=None,
    )]


def _item7a_tables(html: str) -> list[Tag]:
    soup = BeautifulSoup(html, "html.parser")
    tags = soup.find_all(True)
    tag_positions = {id(tag): index for index, tag in enumerate(tags)}

    def heading_candidates(pattern: str, required_phrase: str | None = None) -> list[Tag]:
        candidates: dict[int, Tag] = {}
        for text_node in soup.find_all(string=re.compile(pattern, re.I)):
            parent = text_node.parent
            ancestors = (parent, parent.parent if parent.parent else parent)
            for tag in ancestors:
                if not isinstance(tag, Tag):
                    continue
                text = tag.get_text(" ", strip=True)
                if not re.match(pattern, text, re.I):
                    continue
                if required_phrase and not re.search(required_phrase, text, re.I):
                    continue
                candidates[id(tag)] = tag
        return list(candidates.values())

    start_candidates = heading_candidates(r"\s*item\s+7a\b", r"market risk")
    if not start_candidates:
        return []
    start = min(start_candidates, key=lambda tag: len(tag.get_text(" ", strip=True)))
    start_index = tag_positions[id(start)]
    end_candidates = [
        tag for tag in heading_candidates(r"\s*item\s+8\b")
        if tag_positions[id(tag)] > start_index
    ]
    end_index = min(
        (tag_positions[id(tag)] for tag in end_candidates), default=len(tags)
    )
    return [
        tag for index, tag in enumerate(tags)
        if tag.name == "table" and start_index < index < end_index
    ]


def _table_candidates(tables: list[Tag], fiscal_year: int, section: str) -> list[MarketRiskSensitivity]:
    candidates: list[MarketRiskSensitivity] = []
    year_pattern = re.compile(rf"\b{fiscal_year}\b")
    for table_index, table in enumerate(tables, 1):
        text = re.sub(r"\s+", " ", table.get_text(" ", strip=True))
        grid = expand_table_grid(table)
        if len(grid) < 2:
            continue
        year_columns = {
            index
            for row in grid[:8]
            for index, cell in enumerate(row)
            if year_pattern.search(cell)
        }
        if not year_columns:
            continue

        for row in grid:
            label = _row_label(row).casefold()
            row_text = " ".join(cell for cell in row if cell)
            is_interest_row = label == "interest rate"
            is_investment_portfolio = label == "investment portfolio"
            if not (is_interest_row or is_investment_portfolio):
                continue
            if not re.search(r"basis\s+points?", row_text, re.I):
                continue
            if is_interest_row:
                impact_index = next(
                    (index for index, cell in enumerate(row) if "fair value" in cell.casefold()),
                    None,
                )
                if impact_index is None:
                    continue
                # The sensitivity value precedes the impact label in Microsoft's table.
                value_columns = {index for index in year_columns if index < impact_index}
                scenario = next(
                    (cell.strip() for cell in row if re.search(r"basis\s+points?", cell, re.I)),
                    "interest-rate change",
                )
            else:
                if "decline in fair value" not in row_text.casefold():
                    continue
                value_columns = year_columns
                scenario = next(
                    (cell.strip() for cell in row if re.search(r"basis\s+points?", cell, re.I)),
                    "interest-rate increase",
                )

            values = {
                value
                for index in value_columns
                if index < len(row)
                if (value := parse_sec_amount(row[index])) is not None
            }
            if len(values) != 1:
                continue
            amount = abs(next(iter(values)))
            if amount <= 0:
                continue
            candidates.append(MarketRiskSensitivity(
                fiscal_year=fiscal_year,
                scenario=scenario,
                impact=("fair value of investment portfolio" if is_investment_portfolio
                        else "fair value of fixed-income portfolio"),
                sensitivity_amount=amount,
                unit=("USD millions" if re.search(r"\bmillions\b", text + " " + section, re.I)
                      else "as reported"),
                disclosure=row_text,
                table_index=table_index,
            ))
    return candidates


class MarketRiskSensitivityExtractor:
    """Select a unique Item 7A interest-rate portfolio fair-value sensitivity."""

    def extract(self, html: str, *, fiscal_year: int) -> MarketRiskSensitivity:
        if not html or not html.strip():
            raise ValueError("Filing HTML cannot be empty.")
        if fiscal_year < 1900:
            raise ValueError("fiscal_year must be a valid four-digit year")
        parsed = FilingParser().parse(html)
        sections = [
            section["text"] for section in parsed["sections"]
            if section["heading"].upper().startswith("ITEM 7A")
        ]
        if not sections:
            raise MarketRiskError("The exact 10-K does not expose a readable Item 7A section.")
        section_text = "\n".join(
            section["heading"] + "\n" + section["text"]
            for section in parsed["sections"]
            if section["heading"].upper().startswith("ITEM 7A")
        )
        if not re.search(r"market risk|interest rate", section_text, re.I):
            raise MarketRiskError("Item 7A contains no identifiable interest-rate market-risk disclosure.")

        candidates = _parse_narrative(section_text, fiscal_year)
        candidates.extend(
            _table_candidates(_item7a_tables(html), fiscal_year, section_text)
        )
        unique = {
            (item.scenario.casefold(), item.impact.casefold(), item.sensitivity_amount): item
            for item in candidates
        }
        if len(unique) != 1:
            raise MarketRiskError(
                f"Expected one annual interest-rate investment-portfolio sensitivity; found {len(unique)}."
            )
        result = next(iter(unique.values()))
        if result.unit != "USD millions":
            raise MarketRiskError("The disclosed sensitivity unit could not be normalized safely to USD.")
        return result
