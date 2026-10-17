from decimal import Decimal

import pytest

from finspect.answer_builder import (
    AnswerEvidence,
    build_calculation_answer,
    build_clarification_answer,
    build_unsupported_answer,
)
from finspect.calculator import revenue_growth


def test_calculation_answer_contains_result_formula_and_evidence():
    result = revenue_growth(
        current=Decimal("130"),
        prior=Decimal("100"),
    )

    evidence = [
        AnswerEvidence(
            label="Total revenue",
            value=Decimal("130"),
            unit="USD",
            period="FY2025",
            filing_date="2026-02-25",
            accession_number="0001045810-26-000021",
        ),
        AnswerEvidence(
            label="Total revenue",
            value=Decimal("100"),
            unit="USD",
            period="FY2024",
            filing_date="2025-02-26",
            accession_number="example-prior-accession",
        ),
    ]

    answer = build_calculation_answer(
        company_name="Example Corporation",
        question="Calculate revenue growth from FY2024 to FY2025.",
        result=result,
        evidence=evidence,
    )

    assert "30.00%" in answer.text
    assert result.expression in answer.text
    assert "FY2025" in answer.text
    assert "FY2024" in answer.text
    assert "0001045810-26-000021" in answer.text
    assert answer.formula_id == "Q01"
    assert answer.result_value == "30"


def test_calculation_answer_requires_evidence():
    result = revenue_growth(
        current=Decimal("130"),
        prior=Decimal("100"),
    )

    with pytest.raises(ValueError, match="requires source evidence"):
        build_calculation_answer(
            company_name="Example Corporation",
            question="Calculate revenue growth.",
            result=result,
            evidence=[],
        )


def test_clarification_answer_has_no_calculation():
    answer = build_clarification_answer(
        "Which company and fiscal year do you mean?"
    )

    assert answer.formula_id is None
    assert answer.result_value is None
    assert "clarification" not in answer.text.lower() or "information" in answer.text.lower()


def test_unsupported_answer_explains_limitation():
    answer = build_unsupported_answer(
        "Analyze an unprovided filing.",
        "The requested filing has not been retrieved.",
    )

    assert answer.evidence == ()
    assert "has not been retrieved" in answer.text
