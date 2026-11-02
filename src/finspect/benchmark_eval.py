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
from finspect.calculator import (
    cash_conversion_comparison,
    earnings_change_relationship,
    growth_comparison,
    margin_change,
    revenue_growth,
)
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
DEFAULT_Q13_FIXTURE = ROOT / "data" / "fixtures" / "nvidia_q13_fy2024_fy2025.json"
DEFAULT_Q05_FIXTURE = ROOT / "data" / "fixtures" / "nvidia_q05_fy2024_fy2025.json"
DEFAULT_ANNUAL_REVENUE_MATRIX = (
    ROOT / "data" / "fixtures" / "annual_revenue_reference_matrix.json"
)


def evaluate_annual_revenue_matrix(path: Path) -> dict[str, Any]:
    """Check annual revenue calculations against fixed, cited issuer cases."""
    matrix = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for reference in matrix["cases"]:
        periods = reference["periods"]
        company = reference["company"]
        checks = {
            "two_ordered_periods": len(periods) == 2
            and periods[0]["fiscal_year"] < periods[1]["fiscal_year"],
            "annual_usd_inputs": all(
                item.get("form") == "10-K"
                and item.get("unit") == "USD"
                and item.get("taxonomy") == "us-gaap"
                and item.get("concept") == "Revenues"
                and (date.fromisoformat(item["end_date"])
                     - date.fromisoformat(item["start_date"])).days in range(350, 380)
                for item in periods
            ),
            "evidence_provenance": all(
                item["accession_number"]
                and item["source_url"].startswith(
                    "https://www.sec.gov/Archives/edgar/data/"
                )
                and item["accession_number"].replace("-", "")
                in item["source_url"]
                for item in periods
            ),
            "issuer_metadata": all(
                str(company.get(key, "")).strip()
                for key in ("name", "ticker", "cik")
            ),
        }
        actual = revenue_growth(
            current=Decimal(periods[1]["value"]),
            prior=Decimal(periods[0]["value"]),
        )
        checks["calculation_correctness"] = (
            actual.value == Decimal(reference["expected_growth_percent"])
        )
        passed = all(checks.values())
        cases.append({
            "company": company,
            "fiscal_years": [item["fiscal_year"] for item in periods],
            "input_values_usd": [item["value"] for item in periods],
            "expected_growth_percent": reference["expected_growth_percent"],
            "actual_growth_percent": str(actual.value),
            "evidence": [
                {"accession_number": item["accession_number"],
                 "source_url": item["source_url"]}
                for item in periods
            ],
            "checks": checks,
            "status": "PASS" if passed else "FAIL",
        })
    return {
        "matrix_id": matrix["matrix_id"],
        "question_id": matrix["question_id"],
        "evaluation_scope": matrix["evaluation_scope"],
        "case_count": len(cases),
        "pass_count": sum(item["status"] == "PASS" for item in cases),
        "fail_count": sum(item["status"] == "FAIL" for item in cases),
        "issuers": sorted({item["company"]["ticker"] for item in cases}),
        "cases_per_issuer": {
            ticker: sum(item["company"]["ticker"] == ticker for item in cases)
            for ticker in sorted({item["company"]["ticker"] for item in cases})
        },
        "cases": cases,
    }


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


def _evaluate_q05(question: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    company = fixture["company"]
    periods = fixture["periods"]
    facts_by_metric: dict[str, list[Any]] = {
        "net_income": [],
        "operating_income": [],
    }
    selected_evidence = []
    answer_evidence = []
    for item in periods:
        role = (
            PeriodRole.CURRENT
            if item["role"] == "current"
            else PeriodRole.COMPARABLE_PRIOR
        )
        days = (
            date.fromisoformat(item["end_date"])
            - date.fromisoformat(item["start_date"])
        ).days
        if item["form"] != "10-K" or not 300 <= days <= 400:
            raise ValueError("Q05 fixture periods must be full-year 10-K periods.")
        for metric_name, raw_metric in item.items():
            if metric_name not in facts_by_metric:
                continue
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
            selected_evidence.append({
                "concept": raw_metric["concept"],
                "value": raw_metric["value"],
                "unit": raw_metric["unit"],
                "period_start": item["start_date"],
                "period_end": item["end_date"],
                "form": item["form"],
                "filing_date": item["filing_date"],
                "accession_number": item["accession_number"],
                "source_url": item["source_url"],
                "metric": metric_name,
            })
            answer_evidence.append(AnswerEvidence(
                label=raw_metric["label"],
                value=Decimal(raw_metric["value"]),
                unit=raw_metric["unit"],
                period=f"FY{item['fiscal_year']} ({item['start_date']} to {item['end_date']})",
                filing_date=item["filing_date"],
                accession_number=item["accession_number"],
                source_url=item["source_url"],
            ))

    net_prior, net_current = facts_by_metric["net_income"]
    operating_prior, operating_current = facts_by_metric["operating_income"]
    validate_absolute_change_inputs(net_current, net_prior)
    validate_absolute_change_inputs(operating_current, operating_prior)
    require_compatible_facts(net_current, operating_current)
    require_compatible_facts(net_prior, operating_prior)
    validate_currency_inputs(net_current, net_prior, operating_current, operating_prior)
    result = earnings_change_relationship(
        net_current=net_current.normalized_value,
        net_prior=net_prior.normalized_value,
        operating_current=operating_current.normalized_value,
        operating_prior=operating_prior.normalized_value,
    )
    expected = Decimal(fixture["expected_percent"])
    correct = result.value == expected
    evidence_correct = all(
        item["accession_number"]
        and item["source_url"].startswith("https://www.sec.gov/")
        for item in selected_evidence
    )
    answer = build_calculation_answer(
        company_name=company["name"],
        question=fixture["question"],
        result=result,
        evidence=answer_evidence,
    )
    checks = {
        "input_retrieval_correctness": "not_evaluated_live_retrieval",
        "period_correctness": True,
        "unit_correctness": all(item["unit"] == "USD" for item in selected_evidence),
        "calculation_correctness": correct,
        "evidence_correctness": evidence_correct,
        "query_interpretation_correctness": "not_evaluated",
    }
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
            {"fiscal_year": item["fiscal_year"], "start_date": item["start_date"], "end_date": item["end_date"]}
            for item in periods
        ],
        "expected_concepts": question.required_concepts,
        "retrieval_mode": "checked_in_sec_snapshot_not_live_retrieval",
        "retrieved_inputs": selected_evidence,
        "selected_evidence": selected_evidence,
        "calculation_formula": result.expression,
        "expected_answer": {"percent": str(expected)},
        "actual_answer": {
            "text": answer.text,
            "result_value": answer.result_value,
            "result_unit": answer.result_unit,
        },
        "checks": checks,
        "overall_status": "PARTIAL" if correct and evidence_correct else "FAIL",
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


def _evaluate_q13(question: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    company = fixture["company"]
    periods = fixture["periods"]
    facts_by_metric: dict[str, list[Any]] = {
        "net_income": [],
        "operating_cash_flow": [],
    }
    selected_evidence = []
    answer_evidence = []
    for item in periods:
        role = (
            PeriodRole.CURRENT
            if item["role"] == "current"
            else PeriodRole.COMPARABLE_PRIOR
        )
        days = (
            date.fromisoformat(item["end_date"])
            - date.fromisoformat(item["start_date"])
        ).days
        if item["form"] != "10-K" or not 300 <= days <= 400:
            raise ValueError("Q13 fixture periods must be full-year 10-K periods.")
        for metric_name in facts_by_metric:
            raw_metric = item[metric_name]
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
            selected_evidence.append({
                "concept": raw_metric["concept"],
                "value": raw_metric["value"],
                "unit": raw_metric["unit"],
                "period_start": item["start_date"],
                "period_end": item["end_date"],
                "form": item["form"],
                "filing_date": item["filing_date"],
                "accession_number": item["accession_number"],
                "source_url": item["source_url"],
                "metric": metric_name,
            })
            answer_evidence.append(AnswerEvidence(
                label=raw_metric["label"],
                value=Decimal(raw_metric["value"]),
                unit=raw_metric["unit"],
                period=f"FY{item['fiscal_year']} ({item['start_date']} to {item['end_date']})",
                filing_date=item["filing_date"],
                accession_number=item["accession_number"],
                source_url=item["source_url"],
            ))

    net_prior, net_current = facts_by_metric["net_income"]
    cash_prior, cash_current = facts_by_metric["operating_cash_flow"]
    validate_absolute_change_inputs(net_current, net_prior)
    validate_absolute_change_inputs(cash_current, cash_prior)
    require_compatible_facts(net_current, cash_current)
    require_compatible_facts(net_prior, cash_prior)
    validate_currency_inputs(net_current, net_prior, cash_current, cash_prior)
    if net_current.normalized_value <= 0 or net_prior.normalized_value <= 0:
        raise ValueError("Q13 requires positive net income in both periods.")
    result = cash_conversion_comparison(
        operating_cash_flow_current=cash_current.normalized_value,
        net_income_current=net_current.normalized_value,
        operating_cash_flow_prior=cash_prior.normalized_value,
        net_income_prior=net_prior.normalized_value,
    )
    expected = {
        "current_conversion_percent": Decimal(fixture["expected_current_conversion_percent"]),
        "prior_conversion_percent": Decimal(fixture["expected_prior_conversion_percent"]),
        "change_percentage_points": Decimal(fixture["expected_change_percentage_points"]),
    }
    correct = result.metrics == expected
    evidence_correct = all(
        item["accession_number"]
        and item["source_url"].startswith("https://www.sec.gov/")
        for item in selected_evidence
    )
    checks = {
        "input_retrieval_correctness": "not_evaluated_live_retrieval",
        "period_correctness": True,
        "unit_correctness": all(item["unit"] == "USD" for item in selected_evidence),
        "calculation_correctness": correct,
        "evidence_correctness": evidence_correct,
        "query_interpretation_correctness": "not_evaluated",
    }
    answer = build_calculation_answer(
        company_name=company["name"],
        question=fixture["question"],
        result=result,
        evidence=answer_evidence,
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
            {"fiscal_year": item["fiscal_year"], "start_date": item["start_date"], "end_date": item["end_date"]}
            for item in periods
        ],
        "expected_concepts": question.required_concepts,
        "retrieval_mode": "checked_in_sec_snapshot_not_live_retrieval",
        "retrieved_inputs": selected_evidence,
        "selected_evidence": selected_evidence,
        "calculation_formula": result.expression,
        "expected_answer": {key: str(value) for key, value in expected.items()},
        "actual_answer": {
            "text": answer.text,
            "result_value": answer.result_value,
            "result_unit": answer.result_unit,
            "metrics": {key: str(value) for key, value in result.metrics.items()},
        },
        "checks": checks,
        "overall_status": "PARTIAL" if correct and evidence_correct else "FAIL",
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
    q13_fixture_path: Path = DEFAULT_Q13_FIXTURE,
    q05_fixture_path: Path = DEFAULT_Q05_FIXTURE,
    annual_revenue_matrix_path: Path = DEFAULT_ANNUAL_REVENUE_MATRIX,
) -> dict[str, Any]:
    """Evaluate the current supported fixture and explicitly classify the rest."""
    benchmark = load_benchmark(benchmark_path)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    q03_fixture = json.loads(q03_fixture_path.read_text(encoding="utf-8"))
    q08_fixture = json.loads(q08_fixture_path.read_text(encoding="utf-8"))
    q13_fixture = json.loads(q13_fixture_path.read_text(encoding="utf-8"))
    q05_fixture = json.loads(q05_fixture_path.read_text(encoding="utf-8"))
    annual_revenue_matrix = evaluate_annual_revenue_matrix(
        annual_revenue_matrix_path
    )
    questions = benchmark.question_map()
    if fixture.get("question_id") != "Q01" or "Q01" not in questions:
        raise ValueError("The configured fixture must target benchmark Q01.")
    if q03_fixture.get("question_id") != "Q03" or "Q03" not in questions:
        raise ValueError("The configured fixture must target benchmark Q03.")
    if q08_fixture.get("question_id") != "Q08" or "Q08" not in questions:
        raise ValueError("The configured fixture must target benchmark Q08.")
    if q13_fixture.get("question_id") != "Q13" or "Q13" not in questions:
        raise ValueError("The configured fixture must target benchmark Q13.")
    if q05_fixture.get("question_id") != "Q05" or "Q05" not in questions:
        raise ValueError("The configured fixture must target benchmark Q05.")

    report_questions = []
    for question_id in sorted(questions):
        question = questions[question_id]
        if question_id == "Q05":
            report_questions.append(_evaluate_q05(question, q05_fixture))
            continue
        if question_id == "Q01":
            report_questions.append(_evaluate_q01(question, fixture))
            continue
        if question_id == "Q03":
            report_questions.append(_evaluate_q03(question, q03_fixture))
            continue
        if question_id == "Q08":
            report_questions.append(_evaluate_q08(question, q08_fixture))
            continue
        if question_id == "Q13":
            report_questions.append(_evaluate_q13(question, q13_fixture))
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
            "No overall accuracy percentage is reported: Q01, Q03, Q05, Q08, "
            "and Q13 have fixture-backed pipeline checks; the separate Q01 "
            "issuer matrix checks six cited annual revenue cases, but neither "
            "live SEC retrieval nor the planner was evaluated."
        ),
        "operation_reference_matrices": [annual_revenue_matrix],
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
        "--q13-fixture",
        type=Path,
        default=DEFAULT_Q13_FIXTURE,
        help="Path to the deterministic Q13 filing snapshot.",
    )
    parser.add_argument(
        "--q05-fixture",
        type=Path,
        default=DEFAULT_Q05_FIXTURE,
        help="Path to the deterministic Q05 filing snapshot.",
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
        args.q13_fixture,
        args.q05_fixture,
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
