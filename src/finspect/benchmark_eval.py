"""Reproducible benchmark evaluation using an explicitly labeled SEC snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from finspect.answer_builder import (
    AnswerEvidence,
    build_calculation_answer,
    build_unsupported_answer,
)
from finspect.calculator import growth_comparison, margin_change, revenue_growth
from finspect.edgar.fact_adapter import sec_fact_to_financial_fact
from finspect.schema import (
    PeriodRole,
    ReportingScope,
    load_benchmark,
    require_compatible_facts,
    validate_absolute_change_inputs,
    validate_currency_inputs,
    validate_growth_inputs,
    validate_instant_growth_inputs,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BENCHMARK = ROOT / "data" / "benchmark.json"
DEFAULT_FIXTURE = ROOT / "data" / "fixtures" / "nvidia_q01_fy2024_fy2025.json"
DEFAULT_Q03_FIXTURE = ROOT / "data" / "fixtures" / "nvidia_q03_fy2024_fy2025.json"
DEFAULT_Q08_FIXTURE = ROOT / "data" / "fixtures" / "nvidia_q08_fy2024_fy2025.json"


def _evaluate_q01(question: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    company = fixture["company"]
    periods = fixture["periods"]
    if len(periods) != 2:
        raise ValueError("Q01 fixture must contain exactly two periods.")

    facts = []
    for item in periods:
        raw = {
            "cik": company["cik"],
            "company": "NVIDIA CORP",
            "taxonomy": item["taxonomy"],
            "concept": item["concept"],
            "label": item["label"],
            "value": item["value"],
            "unit": item["unit"],
            "start_date": item["start_date"],
            "end_date": item["end_date"],
            "fiscal_year": item["fiscal_year"],
            "form": item["form"],
            "filing_date": item["filing_date"],
            "accession_number": item["accession_number"],
        }
        role = (
            PeriodRole.CURRENT
            if item["role"] == "current"
            else PeriodRole.COMPARABLE_PRIOR
        )
        facts.append(
            sec_fact_to_financial_fact(
                raw,
                period_role=role,
                reporting_scope=ReportingScope.CONSOLIDATED,
            ).model_copy(update={"entity": company["name"]})
        )

    prior, current = facts
    validate_growth_inputs(current, prior)
    result = revenue_growth(
        current=current.normalized_value,
        prior=prior.normalized_value,
    )
    expected_value = Decimal(fixture["expected_growth_percent"])
    correct_result = result.value == expected_value

    selected_evidence = [
        {
            "concept": item["concept"],
            "value": item["value"],
            "unit": item["unit"],
            "period_start": item["start_date"],
            "period_end": item["end_date"],
            "form": item["form"],
            "filing_date": item["filing_date"],
            "accession_number": item["accession_number"],
            "source_url": item["source_url"],
        }
        for item in periods
    ]
    answer = build_calculation_answer(
        company_name=company["name"],
        question=fixture["question"],
        result=result,
        evidence=tuple(
            AnswerEvidence(
                label=item["label"],
                value=Decimal(item["value"]),
                unit=item["unit"],
                period=f"FY{item['fiscal_year']} ({item['start_date']} to {item['end_date']})",
                filing_date=item["filing_date"],
                accession_number=item["accession_number"],
                source_url=item["source_url"],
            )
            for item in periods
        ),
    )
    evidence_valid = all(
        item["accession_number"] and item["source_url"].startswith("https://www.sec.gov/")
        for item in selected_evidence
    )
    periods_valid = all(
        item["form"] == "10-K"
        and item["unit"] == "USD"
        and item["fiscal_year"] in {2024, 2025}
        for item in periods
    )
    checks = {
        "input_retrieval_correctness": "not_evaluated_live_retrieval",
        "period_correctness": periods_valid,
        "unit_correctness": periods_valid,
        "calculation_correctness": correct_result,
        "evidence_correctness": evidence_valid,
        "query_interpretation_correctness": "not_evaluated",
    }
    status = "PARTIAL" if all(
        value is True
        for key, value in checks.items()
        if key not in {
            "query_interpretation_correctness",
            "input_retrieval_correctness",
        }
    ) else "FAIL"

    return {
        "question_id": question.id,
        "question": fixture["question"],
        "company": company,
        "filings": [
            {
                "form": item["form"],
                "filing_date": item["filing_date"],
                "accession_number": item["accession_number"],
                "url": item["source_url"],
            }
            for item in periods
        ],
        "reporting_periods": [
            {
                "fiscal_year": item["fiscal_year"],
                "start_date": item["start_date"],
                "end_date": item["end_date"],
            }
            for item in periods
        ],
        "expected_concepts": question.required_concepts,
        "retrieval_mode": "checked_in_sec_snapshot_not_live_retrieval",
        "retrieved_inputs": [
            {
                "concept": item["concept"],
                "value": item["value"],
                "unit": item["unit"],
                "period_end": item["end_date"],
            }
            for item in periods
        ],
        "selected_evidence": selected_evidence,
        "calculation_formula": result.expression,
        "expected_answer": {
            "growth_percent": str(expected_value),
            "display": f"{expected_value.quantize(Decimal('0.01'))}%",
        },
        "actual_answer": {
            "text": answer.text,
            "result_value": answer.result_value,
            "result_unit": answer.result_unit,
        },
        "checks": checks,
        "overall_status": status,
        "failure_reason": (
            "Query interpretation and live SEC retrieval were not tested; "
            "the validated plan and filing facts came from deterministic fixtures."
        ),
    }


def _evaluate_q03(question: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    company = fixture["company"]
    periods = fixture["periods"]
    facts_by_metric: dict[str, list[Any]] = {
        "revenue": [],
        "operating_income": [],
    }
    for item in periods:
        role = (
            PeriodRole.CURRENT
            if item["role"] == "current"
            else PeriodRole.COMPARABLE_PRIOR
        )
        for metric_name, raw_metric in item["facts"].items():
            raw = {
                "cik": company["cik"],
                "company": "NVIDIA CORP",
                **raw_metric,
                "start_date": item["start_date"],
                "end_date": item["end_date"],
                "fiscal_year": item["fiscal_year"],
                "form": item["form"],
                "filing_date": item["filing_date"],
                "accession_number": item["accession_number"],
            }
            fact = sec_fact_to_financial_fact(
                raw,
                period_role=role,
                reporting_scope=ReportingScope.CONSOLIDATED,
            ).model_copy(update={"entity": company["name"]})
            facts_by_metric[metric_name].append(fact)

    revenue_prior, revenue_current = facts_by_metric["revenue"]
    income_prior, income_current = facts_by_metric["operating_income"]
    validate_absolute_change_inputs(revenue_current, revenue_prior)
    validate_absolute_change_inputs(income_current, income_prior)
    require_compatible_facts(revenue_current, income_current)
    require_compatible_facts(revenue_prior, income_prior)
    validate_currency_inputs(
        revenue_current,
        revenue_prior,
        income_current,
        income_prior,
    )
    result = margin_change(
        current_income=income_current.normalized_value,
        current_revenue=revenue_current.normalized_value,
        prior_income=income_prior.normalized_value,
        prior_revenue=revenue_prior.normalized_value,
    )
    expected_value = Decimal(fixture["expected_margin_change_percentage_points"])
    correct_result = result.value == expected_value

    selected_evidence = []
    for item in periods:
        for metric_name, fact in item["facts"].items():
            selected_evidence.append({
                "concept": fact["concept"],
                "value": fact["value"],
                "unit": fact["unit"],
                "period_start": item["start_date"],
                "period_end": item["end_date"],
                "form": item["form"],
                "filing_date": item["filing_date"],
                "accession_number": item["accession_number"],
                "source_url": item["source_url"],
                "metric": metric_name,
            })
    evidence_valid = all(
        item["accession_number"]
        and item["source_url"].startswith("https://www.sec.gov/")
        for item in selected_evidence
    )
    periods_valid = all(
        item["form"] == "10-K"
        and 300 <= (
            date.fromisoformat(item["end_date"])
            - date.fromisoformat(item["start_date"])
        ).days <= 400
        for item in periods
    )
    checks = {
        "input_retrieval_correctness": "not_evaluated_live_retrieval",
        "period_correctness": periods_valid,
        "unit_correctness": all(
            fact["unit"] == "USD"
            for item in periods
            for fact in item["facts"].values()
        ),
        "calculation_correctness": correct_result,
        "evidence_correctness": evidence_valid,
        "query_interpretation_correctness": "not_evaluated",
    }
    status = "PARTIAL" if all(
        value is True
        for key, value in checks.items()
        if key not in {
            "query_interpretation_correctness",
            "input_retrieval_correctness",
        }
    ) else "FAIL"
    answer = build_calculation_answer(
        company_name=company["name"],
        question=fixture["question"],
        result=result,
        evidence=tuple(
            AnswerEvidence(
                label=fact["label"],
                value=Decimal(fact["value"]),
                unit=fact["unit"],
                period=f"FY{item['fiscal_year']} ({item['start_date']} to {item['end_date']})",
                filing_date=item["filing_date"],
                accession_number=item["accession_number"],
                source_url=item["source_url"],
            )
            for item in periods
            for fact in item["facts"].values()
        ),
    )
    return {
        "question_id": question.id,
        "question": fixture["question"],
        "company": company,
        "filings": [
            {
                "form": item["form"],
                "filing_date": item["filing_date"],
                "accession_number": item["accession_number"],
                "url": item["source_url"],
            }
            for item in periods
        ],
        "reporting_periods": [
            {
                "fiscal_year": item["fiscal_year"],
                "start_date": item["start_date"],
                "end_date": item["end_date"],
            }
            for item in periods
        ],
        "expected_concepts": question.required_concepts,
        "retrieval_mode": "checked_in_sec_snapshot_not_live_retrieval",
        "retrieved_inputs": selected_evidence,
        "selected_evidence": selected_evidence,
        "calculation_formula": result.expression,
        "expected_answer": {
            "margin_change_percentage_points": str(expected_value),
            "display": f"{expected_value.quantize(Decimal('0.01'))} percentage points",
        },
        "actual_answer": {
            "text": answer.text,
            "result_value": answer.result_value,
            "result_unit": answer.result_unit,
        },
        "checks": checks,
        "overall_status": status,
        "failure_reason": (
            "Query interpretation and live SEC retrieval were not tested; "
            "the validated plan and filing facts came from deterministic fixtures."
        ),
    }


def _evaluate_q08(question: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    company = fixture["company"]
    periods = fixture["periods"]
    facts_by_metric: dict[str, list[Any]] = {
        "revenue": [],
        "accounts_receivable": [],
    }
    for item in periods:
        role = (
            PeriodRole.CURRENT
            if item["role"] == "current"
            else PeriodRole.COMPARABLE_PRIOR
        )
        for metric_name in facts_by_metric:
            raw_metric = item[metric_name]
            raw = {
                "cik": company["cik"],
                "company": "NVIDIA CORP",
                **raw_metric,
                "start_date": (
                    item["start_date"]
                    if raw_metric["period_kind"] == "duration"
                    else None
                ),
                "end_date": item["end_date"],
                "fiscal_year": item["fiscal_year"],
                "form": item["form"],
                "filing_date": item["filing_date"],
                "accession_number": item["accession_number"],
            }
            fact = sec_fact_to_financial_fact(
                raw,
                period_role=role,
                reporting_scope=ReportingScope.CONSOLIDATED,
            ).model_copy(update={"entity": company["name"]})
            facts_by_metric[metric_name].append(fact)

    revenue_prior, revenue_current = facts_by_metric["revenue"]
    receivables_prior, receivables_current = facts_by_metric["accounts_receivable"]
    validate_growth_inputs(revenue_current, revenue_prior)
    validate_instant_growth_inputs(receivables_current, receivables_prior)
    if (
        revenue_current.period.end_date != receivables_current.period.end_date
        or revenue_prior.period.end_date != receivables_prior.period.end_date
    ):
        raise ValueError("Q08 snapshot balance-sheet dates do not match fiscal year ends.")
    require_compatible_facts(
        revenue_current,
        receivables_current,
        require_same_period=False,
    )
    require_compatible_facts(
        revenue_prior,
        receivables_prior,
        require_same_period=False,
    )
    validate_currency_inputs(
        revenue_current,
        revenue_prior,
        receivables_current,
        receivables_prior,
    )
    result = growth_comparison(
        ar_current=receivables_current.normalized_value,
        ar_prior=receivables_prior.normalized_value,
        revenue_current=revenue_current.normalized_value,
        revenue_prior=revenue_prior.normalized_value,
    )
    expected_value = Decimal(fixture["expected_growth_difference_percentage_points"])
    correct_result = result.value == expected_value

    selected_evidence = []
    for item in periods:
        for metric_name in facts_by_metric:
            fact = item[metric_name]
            selected_evidence.append({
                "concept": fact["concept"],
                "value": fact["value"],
                "unit": fact["unit"],
                "period_start": item["start_date"] if metric_name == "revenue" else None,
                "period_end": item["end_date"],
                "form": item["form"],
                "filing_date": item["filing_date"],
                "accession_number": item["accession_number"],
                "source_url": item["source_url"],
                "metric": metric_name,
            })
    evidence_valid = all(
        item["accession_number"]
        and item["source_url"].startswith("https://www.sec.gov/")
        for item in selected_evidence
    )
    checks = {
        "input_retrieval_correctness": "not_evaluated_live_retrieval",
        "period_correctness": evidence_valid,
        "unit_correctness": all(
            item[metric]["unit"] == "USD"
            for item in periods
            for metric in facts_by_metric
        ),
        "calculation_correctness": correct_result,
        "evidence_correctness": evidence_valid,
        "query_interpretation_correctness": "not_evaluated",
    }
    status = "PARTIAL" if all(
        value is True
        for key, value in checks.items()
        if key not in {
            "query_interpretation_correctness",
            "input_retrieval_correctness",
        }
    ) else "FAIL"
    answer = build_calculation_answer(
        company_name=company["name"],
        question=fixture["question"],
        result=result,
        evidence=tuple(
            AnswerEvidence(
                label=item[metric]["label"],
                value=Decimal(item[metric]["value"]),
                unit=item[metric]["unit"],
                period=f"FY{item['fiscal_year']} ({item['start_date']} to {item['end_date']})",
                filing_date=item["filing_date"],
                accession_number=item["accession_number"],
                source_url=item["source_url"],
            )
            for item in periods
            for metric in facts_by_metric
        ),
    )
    return {
        "question_id": question.id,
        "question": fixture["question"],
        "company": company,
        "filings": [
            {
                "form": item["form"],
                "filing_date": item["filing_date"],
                "accession_number": item["accession_number"],
                "url": item["source_url"],
            }
            for item in periods
        ],
        "reporting_periods": [
            {
                "fiscal_year": item["fiscal_year"],
                "start_date": item["start_date"],
                "end_date": item["end_date"],
            }
            for item in periods
        ],
        "expected_concepts": question.required_concepts,
        "retrieval_mode": "checked_in_sec_snapshot_not_live_retrieval",
        "retrieved_inputs": selected_evidence,
        "selected_evidence": selected_evidence,
        "calculation_formula": result.expression,
        "expected_answer": {
            "growth_difference_percentage_points": str(expected_value),
            "display": f"{expected_value.quantize(Decimal('0.01'))} percentage points",
        },
        "actual_answer": {
            "text": answer.text,
            "result_value": answer.result_value,
            "result_unit": answer.result_unit,
        },
        "checks": checks,
        "overall_status": status,
        "failure_reason": (
            "Query interpretation and live SEC retrieval were not tested; "
            "the validated plan and filing facts came from deterministic fixtures."
        ),
    }


def evaluate_benchmark(
    benchmark_path: Path = DEFAULT_BENCHMARK,
    fixture_path: Path = DEFAULT_FIXTURE,
    q03_fixture_path: Path = DEFAULT_Q03_FIXTURE,
    q08_fixture_path: Path = DEFAULT_Q08_FIXTURE,
) -> dict[str, Any]:
    """Evaluate the current supported fixture and explicitly classify the rest."""
    benchmark = load_benchmark(benchmark_path)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    q03_fixture = json.loads(q03_fixture_path.read_text(encoding="utf-8"))
    q08_fixture = json.loads(q08_fixture_path.read_text(encoding="utf-8"))
    questions = benchmark.question_map()
    if fixture.get("question_id") != "Q01" or "Q01" not in questions:
        raise ValueError("The configured fixture must target benchmark Q01.")
    if q03_fixture.get("question_id") != "Q03" or "Q03" not in questions:
        raise ValueError("The configured fixture must target benchmark Q03.")
    if q08_fixture.get("question_id") != "Q08" or "Q08" not in questions:
        raise ValueError("The configured fixture must target benchmark Q08.")

    report_questions = []
    for question_id in sorted(questions):
        question = questions[question_id]
        if question_id == "Q01":
            report_questions.append(_evaluate_q01(question, fixture))
            continue
        if question_id == "Q03":
            report_questions.append(_evaluate_q03(question, q03_fixture))
            continue
        if question_id == "Q08":
            report_questions.append(_evaluate_q08(question, q08_fixture))
            continue

        reason = (
            "No complete retrieval-to-answer path is implemented for "
            f"{question_id}; calculator registration alone is not support."
        )
        unsupported = build_unsupported_answer(
            question=question.question_template,
            reason=reason,
        )
        report_questions.append({
            "question_id": question_id,
            "question": question.question_template,
            "company": None,
            "filings": [],
            "reporting_periods": question.required_periods,
            "expected_concepts": question.required_concepts,
            "retrieval_mode": "not_run",
            "retrieved_inputs": [],
            "selected_evidence": [],
            "calculation_formula": (
                question.calculation.get("formula")
                if question.calculation else None
            ),
            "expected_answer": None,
            "actual_answer": unsupported.text,
            "checks": {
                "input_retrieval_correctness": None,
                "period_correctness": None,
                "unit_correctness": None,
                "calculation_correctness": None,
                "evidence_correctness": None,
                "query_interpretation_correctness": None,
            },
            "overall_status": "UNSUPPORTED",
            "failure_reason": reason,
        })

    counts = {
        status: sum(item["overall_status"] == status for item in report_questions)
        for status in ("PASS", "PARTIAL", "UNSUPPORTED", "FAIL")
    }
    return {
        "benchmark_name": benchmark.benchmark.get("name"),
        "benchmark_version": benchmark.benchmark.get("version"),
        "evaluation_method": "deterministic SEC snapshot plus current pipeline coverage",
        "live_sec_integration_tested": False,
        "live_query_planner_tested": False,
        "question_count": len(report_questions),
        "aggregate_counts": counts,
        "accuracy_percentage": None,
        "accuracy_note": (
            "No accuracy percentage is reported: the benchmark is company-agnostic, "
            "only Q01, Q03, and Q08 have checked-in filing snapshots, and the planner was not run live."
        ),
        "questions": report_questions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=DEFAULT_BENCHMARK,
        help="Path to the benchmark JSON.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Path to the deterministic Q01 filing snapshot.",
    )
    parser.add_argument(
        "--q03-fixture",
        type=Path,
        default=DEFAULT_Q03_FIXTURE,
        help="Path to the deterministic Q03 filing snapshot.",
    )
    parser.add_argument(
        "--q08-fixture",
        type=Path,
        default=DEFAULT_Q08_FIXTURE,
        help="Path to the deterministic Q08 filing snapshot.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "benchmark-report.json",
        help="Where to write the reproducible JSON report.",
    )
    args = parser.parse_args()

    report = evaluate_benchmark(
        args.benchmark,
        args.fixture,
        args.q03_fixture,
        args.q08_fixture,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "Benchmark report written to "
        f"{args.output}: {report['aggregate_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
