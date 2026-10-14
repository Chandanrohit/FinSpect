from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from finspect.calculator import CalculationResult


@dataclass(frozen=True, slots=True)
class AnswerEvidence:
    """Source metadata attached to a retrieved input fact."""

    label: str
    value: Decimal
    unit: str
    period: str
    filing_date: str
    accession_number: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class Answer:
    """User-facing answer plus structured provenance."""

    text: str
    formula_id: str | None
    result_value: str | None
    result_unit: str | None
    evidence: tuple[AnswerEvidence, ...]
    limitations: tuple[str, ...] = ()


def _format_decimal(value: Decimal) -> str:
    """Avoid scientific notation for ordinary financial values."""
    return format(value, ",f")


def build_calculation_answer(
    *,
    company_name: str,
    question: str,
    result: CalculationResult,
    evidence: Sequence[AnswerEvidence],
    limitations: Sequence[str] = (),
) -> Answer:
    """
    Format an already-computed result.

    This function does not retrieve facts, validate accounting periods,
    or calculate the result. Those responsibilities belong upstream.
    """
    if not evidence:
        raise ValueError(
            "A calculation answer requires source evidence for its inputs."
        )

    if result.value is None:
        raise ValueError("Cannot present a calculation with no result value.")

    value_text = _format_decimal(result.value)
    unit_text = result.unit

    if result.unit == "percent":
        value_text += "%"

    lines = [
        f"Question: {question}",
        "",
        f"Result: {company_name}'s result is {value_text}.",
        "",
        f"Formula: {result.expression}",
        f"Calculation ID: {result.formula_id}",
        f"Calculation source: {result.source.value}",
        "",
        "Inputs:",
    ]

    for name, value in result.inputs.items():
        lines.append(f"- {name}: {_format_decimal(value)}")

    lines.extend(["", "Evidence:"])

    for item in evidence:
        filing = f"filed {item.filing_date}" if item.filing_date else "filing date unavailable"
        lines.append(
            f"- {item.label}: {_format_decimal(item.value)} {item.unit}; "
            f"period {item.period}; {filing}."
        )

        if item.source_url:
            lines.append(f"  Source: {item.source_url}")
        elif item.accession_number:
            lines.append(f"  SEC accession number: {item.accession_number}")

    if result.notes:
        lines.extend(["", "Calculation notes:"])
        lines.extend(f"- {note}" for note in result.notes)

    if limitations:
        lines.extend(["", "Limitations:"])
        lines.extend(f"- {item}" for item in limitations)

    return Answer(
        text="\n".join(lines),
        formula_id=result.formula_id,
        result_value=str(result.value),
        result_unit=unit_text,
        evidence=tuple(evidence),
        limitations=tuple(limitations),
    )


def build_clarification_answer(question: str) -> Answer:
    """Return a safe response when the planner needs clarification."""
    return Answer(
        text=(
            "I need a little more information before answering reliably.\n\n"
            f"Your question: {question}"
        ),
        formula_id=None,
        result_value=None,
        result_unit=None,
        evidence=(),
        limitations=("No financial calculation was performed.",),
    )


def build_unsupported_answer(
    question: str,
    reason: str,
) -> Answer:
    """Explain why the current pipeline cannot answer a request."""
    return Answer(
        text=(
            f"I cannot answer this request reliably yet: {reason}\n\n"
            f"Your question: {question}"
        ),
        formula_id=None,
        result_value=None,
        result_unit=None,
        evidence=(),
        limitations=(reason,),
    )
