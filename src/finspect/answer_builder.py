from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from finspect.calculator import CalculationResult


@dataclass(frozen=True, slots=True)
class AnswerEvidence:
    """Source metadata attached to a retrieved input fact."""

    label: str
    value: Decimal | str
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

def _format_result(value: Decimal, unit: str) -> str:
    """Format results for display without changing stored precision."""
    if unit == "percent":
        return f"{value.quantize(Decimal('0.01')):,.2f}%"
    if unit == "percentage_points":
        return (
            f"{value.quantize(Decimal('0.01')):,.2f} "
            "percentage points"
        )

    return _format_decimal(value)

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


    value_text = _format_result(result.value, result.unit)
    unit_text = result.unit

    if result.metrics and result.formula_id == "Q13":
        current = result.metrics["current_conversion_percent"]
        prior = result.metrics["prior_conversion_percent"]
        change = result.metrics["change_percentage_points"]
        if change > 0:
            change_description = "increase"
        elif change < 0:
            change_description = "decrease"
        else:
            change_description = "no change"
        result_line = (
            f"Current period cash conversion was {_format_result(current, 'percent')}; "
            f"the comparable prior period was {_format_result(prior, 'percent')}. "
            f"That is a {abs(change).quantize(Decimal('0.01')):,.2f} "
            f"percentage-point {change_description}."
        )
    elif result.formula_id == "Q12":
        component_name = next(
            name for name in result.inputs if name != "ending_equity"
        )
        amount = result.inputs[component_name]
        result_line = (
            f"The largest disclosed equity change was {component_name} at "
            f"${amount:,.0f}, or {_format_result(result.value, 'percent')} of ending equity."
        )
    elif result.formula_id == "Q02":
        selected_segment = next(
            note.removeprefix("selected_segment=")
            for note in result.notes
            if note.startswith("selected_segment=")
        )
        result_line = (
            f"{selected_segment} had the largest disclosed business-segment revenue increase, "
            f"contributing {_format_result(result.value, 'percent')} of the total revenue increase."
        )
    elif result.formula_id == "Q14":
        allocated = sum(
            result.inputs[name]
            for name in ("share_repurchase", "dividends", "capital_expenditure")
        )
        result_line = (
            f"{company_name} used "
            f"${allocated:,.0f}, equal to {_format_result(result.value, 'percent')} "
            "of operating cash flow for share repurchases, dividends, and capital expenditure."
        )
    elif result.formula_id == "Q15":
        near = result.inputs["near_term_commitments"]
        total = result.inputs["total_commitments"]
        liquid = result.inputs["liquid_resources"]
        near_share = near / total * Decimal(100)
        result_line = (
            f"{company_name} disclosed ${total:,.0f} in total commitments, of which "
            f"${near:,.0f} ({near_share.quantize(Decimal('0.01')):,.2f}%) is due in the next fiscal year. "
            f"Reported cash and short-term investments of ${liquid:,.0f} cover those near-term commitments "
            f"{result.value.quantize(Decimal('0.01')):,.2f} times."
        )
    elif result.formula_id == "Q06":
        change = result.value or Decimal(0)
        direction = "increased" if change > 0 else "decreased" if change < 0 else "was unchanged"
        disclosed_rows = sorted(
            (
                item for item in evidence
                if item.label not in {
                    "Beginning shareholders’ equity", "Ending shareholders’ equity"
                }
            ),
            key=lambda item: abs(item.value),
            reverse=True,
        )[:3]
        row_summary = "; principal disclosed changes include " + ", ".join(
            f"{item.label} (${item.value:,.0f})" for item in disclosed_rows
        ) if disclosed_rows else ""
        result_line = (
            f"{company_name}'s shareholders’ equity {direction} by "
            f"${abs(change):,.0f}{row_summary}."
        )
    else:
        result_line = f"{company_name}'s result is {value_text}."


    lines = [
        f"Question: {question}",
        "",
        f"Result: {result_line}",
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


def build_narrative_answer(
    *,
    company_name: str,
    question: str,
    topic: str,
    evidence: Sequence[AnswerEvidence],
    limitations: Sequence[str] = (),
) -> Answer:
    """Build a qualitative answer from cited, retrieved filing passages."""
    if not evidence:
        raise ValueError("A narrative answer requires filing evidence.")
    lines = [
        f"Question: {question}",
        "",
        f"Result: {company_name}'s filing contains {len(evidence)} relevant "
        f"{topic} disclosure passage(s). The excerpts below describe risks "
        "the company identifies; they are not predictions.",
        "",
        "Selected filing evidence:",
    ]
    for item in evidence:
        excerpt = str(item.value).strip()
        source = f" [SEC Form 10-K]({item.source_url})" if item.source_url else ""
        lines.append(f"- **{item.label}:** “{excerpt}”{source}")
    if limitations:
        lines.extend(["", "Limitations:"])
        lines.extend(f"- {item}" for item in limitations)
    return Answer(
        text="\n".join(lines),
        formula_id=None,
        result_value=None,
        result_unit=None,
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
