from finspect.benchmark_eval import evaluate_benchmark, evaluate_commitment_matrix
from pathlib import Path


def test_commitment_reference_matrix_covers_three_issuers_and_two_years():
    path = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "annual_commitment_reference_matrix.json"
    result = evaluate_commitment_matrix(path)
    assert result["case_count"] == result["pass_count"] == 6
    assert result["minimum_gate_coverage_met"] is True


def test_benchmark_report_records_fixture_and_unsupported_questions():
    report = evaluate_benchmark()

    assert report["question_count"] == 20
    assert report["aggregate_counts"] == {
        "PASS": 0,
        "PARTIAL": 14,
        "UNSUPPORTED": 6,
        "FAIL": 0,
    }
    assert report["accuracy_percentage"] is None
    assert report["live_sec_integration_tested"] is False
    assert report["live_query_planner_tested"] is False

    revenue_matrix = report["operation_reference_matrices"][0]
    assert revenue_matrix["question_id"] == "Q01"
    assert revenue_matrix["case_count"] == 8
    assert revenue_matrix["pass_count"] == 8
    assert revenue_matrix["fail_count"] == 0
    assert revenue_matrix["issuers"] == ["AAPL", "CVS", "MSFT", "NVDA"]
    assert set(revenue_matrix["cases_per_issuer"].values()) == {2}

    margin_matrix = report["operation_reference_matrices"][1]
    assert margin_matrix["question_id"] == "Q03"
    assert margin_matrix["case_count"] == 8
    assert margin_matrix["pass_count"] == 8
    assert margin_matrix["fail_count"] == 0
    assert margin_matrix["issuers"] == ["AAPL", "CVS", "MSFT", "NVDA"]
    assert set(margin_matrix["cases_per_issuer"].values()) == {2}

    earnings_matrix = report["operation_reference_matrices"][2]
    assert earnings_matrix["question_id"] == "Q05"
    assert earnings_matrix["case_count"] == 8
    assert earnings_matrix["pass_count"] == 8
    assert earnings_matrix["fail_count"] == 0
    assert earnings_matrix["issuers"] == ["AAPL", "CVS", "MSFT", "NVDA"]
    assert set(earnings_matrix["cases_per_issuer"].values()) == {2}

    liquidity_matrix = report["operation_reference_matrices"][3]
    assert liquidity_matrix["question_id"] == "Q07"
    assert liquidity_matrix["case_count"] == 8
    assert liquidity_matrix["pass_count"] == 8
    assert liquidity_matrix["fail_count"] == 0
    assert liquidity_matrix["issuers"] == ["AAPL", "MSFT", "NVDA", "PEP"]
    assert set(liquidity_matrix["cases_per_issuer"].values()) == {2}

    cash_conversion_matrix = report["operation_reference_matrices"][4]
    assert cash_conversion_matrix["question_id"] == "Q13"
    assert cash_conversion_matrix["case_count"] == 8
    assert cash_conversion_matrix["pass_count"] == 8
    assert cash_conversion_matrix["fail_count"] == 0
    assert cash_conversion_matrix["issuers"] == ["AAPL", "CVS", "MSFT", "NVDA"]
    assert set(cash_conversion_matrix["cases_per_issuer"].values()) == {2}

    receivables_matrix = report["operation_reference_matrices"][5]
    assert receivables_matrix["question_id"] == "Q08"
    assert receivables_matrix["case_count"] == 6
    assert receivables_matrix["pass_count"] == 6
    assert receivables_matrix["fail_count"] == 0
    assert receivables_matrix["issuers"] == ["AAPL", "MSFT", "NVDA"]
    assert set(receivables_matrix["cases_per_issuer"].values()) == {2}

    inventory_matrix = report["operation_reference_matrices"][6]
    assert inventory_matrix["question_id"] == "Q09"
    assert inventory_matrix["case_count"] == inventory_matrix["pass_count"] == 6
    assert inventory_matrix["fail_count"] == 0
    assert inventory_matrix["issuers"] == ["AAPL", "MSFT", "NVDA"]
    assert set(inventory_matrix["cases_per_issuer"].values()) == {2}

    dilution_matrix = report["operation_reference_matrices"][7]
    assert dilution_matrix["question_id"] == "Q11"
    assert dilution_matrix["case_count"] == dilution_matrix["pass_count"] == 9
    assert dilution_matrix["fail_count"] == 0
    assert dilution_matrix["issuers"] == ["AAPL", "MSFT", "NVDA"]
    assert set(dilution_matrix["cases_per_issuer"].values()) == {3}

    repurchase_matrix = report["operation_reference_matrices"][8]
    assert repurchase_matrix["question_id"] == "Q10"
    assert repurchase_matrix["case_count"] == repurchase_matrix["pass_count"] == 8
    assert repurchase_matrix["fail_count"] == 0
    assert repurchase_matrix["issuers"] == ["AAPL", "CVS", "MSFT", "NVDA"]
    assert set(repurchase_matrix["cases_per_issuer"].values()) == {2}
    cvs_zero_spend = next(
        case for case in repurchase_matrix["cases"]
        if case["company"]["ticker"] == "CVS"
        and case["fiscal_years"] == [2024, 2025]
    )
    assert cvs_zero_spend["status"] == "PASS"
    assert cvs_zero_spend["actual_current_ratio_percent"] == "0"
    assert cvs_zero_spend["actual_change_amount"] == "-3023000000"

    equity_matrix = report["operation_reference_matrices"][9]
    assert equity_matrix["question_id"] == "Q12"
    assert equity_matrix["case_count"] == equity_matrix["pass_count"] == 6
    assert equity_matrix["fail_count"] == 0
    assert equity_matrix["issuers"] == ["AAPL", "MSFT", "NVDA"]
    assert equity_matrix["minimum_gate_coverage_met"] is True
    assert set(equity_matrix["cases_per_issuer"].values()) == {2}
    apple_case = next(
        case for case in equity_matrix["cases"]
        if case["company"]["ticker"] == "AAPL"
        and case["fiscal_year"] == 2025
    )
    assert apple_case["actual_largest_component"] == "Net income"
    assert apple_case["actual_contribution_percent"] == (
        "151.9129833317510476991306471"
    )
    apple_buyback_case = next(
        case for case in equity_matrix["cases"]
        if case["company"]["ticker"] == "AAPL"
        and case["fiscal_year"] == 2024
    )
    assert apple_buyback_case["actual_largest_component"] == "Common stock repurchased"
    assert apple_buyback_case["actual_contribution_percent"].startswith("-168.29")

    cash_allocation_matrix = report["operation_reference_matrices"][10]
    assert cash_allocation_matrix["question_id"] == "Q14"
    assert cash_allocation_matrix["case_count"] == cash_allocation_matrix["pass_count"] == 6
    assert cash_allocation_matrix["fail_count"] == 0
    assert cash_allocation_matrix["issuers"] == ["AAPL", "MSFT", "NVDA"]
    assert cash_allocation_matrix["minimum_gate_coverage_met"] is True
    assert set(cash_allocation_matrix["cases_per_issuer"].values()) == {2}

    equity_rollforward_matrix = report["operation_reference_matrices"][11]
    assert equity_rollforward_matrix["question_id"] == "Q06"
    assert equity_rollforward_matrix["case_count"] == equity_rollforward_matrix["pass_count"] == 6
    assert equity_rollforward_matrix["fail_count"] == 0
    assert equity_rollforward_matrix["issuers"] == ["AAPL", "MSFT", "NVDA"]
    assert equity_rollforward_matrix["minimum_gate_coverage_met"] is True
    assert set(equity_rollforward_matrix["cases_per_issuer"].values()) == {2}

    regulatory_risk_matrix = report["operation_reference_matrices"][12]
    assert regulatory_risk_matrix["question_id"] == "Q16"
    assert regulatory_risk_matrix["case_count"] == regulatory_risk_matrix["pass_count"] == 6
    assert regulatory_risk_matrix["fail_count"] == 0
    assert regulatory_risk_matrix["issuers"] == ["AAPL", "MSFT", "NVDA"]
    assert regulatory_risk_matrix["minimum_gate_coverage_met"] is True
    assert set(regulatory_risk_matrix["cases_per_issuer"].values()) == {2}

    commitment_matrix = report["operation_reference_matrices"][13]
    assert commitment_matrix["question_id"] == "Q15"
    assert commitment_matrix["case_count"] == commitment_matrix["pass_count"] == 6
    assert commitment_matrix["minimum_gate_coverage_met"] is True

    questions = {item["question_id"]: item for item in report["questions"]}
    q01 = questions["Q01"]
    assert q01["overall_status"] == "PARTIAL"
    assert q01["actual_answer"]["result_unit"] == "percent"
    assert q01["expected_answer"]["display"] == "114.20%"
    assert q01["checks"]["calculation_correctness"] is True
    assert q01["checks"]["evidence_correctness"] is True
    assert q01["checks"]["input_retrieval_correctness"] == (
        "not_evaluated_live_retrieval"
    )
    assert len(q01["selected_evidence"]) == 2

    q03 = questions["Q03"]
    assert q03["overall_status"] == "PARTIAL"
    assert q03["actual_answer"]["result_unit"] == "percentage_points"
    assert q03["expected_answer"]["display"] == "8.30 percentage points"
    assert q03["checks"]["calculation_correctness"] is True
    assert len(q03["selected_evidence"]) == 4

    q05 = questions["Q05"]
    assert q05["overall_status"] == "PARTIAL"
    assert q05["actual_answer"]["result_unit"] == "percent"
    assert q05["expected_answer"]["percent"] == "88.94205977599471958086673130"
    assert q05["checks"]["calculation_correctness"] is True
    assert len(q05["selected_evidence"]) == 4

    q07 = questions["Q07"]
    assert q07["overall_status"] == "PARTIAL"
    assert q07["actual_answer"]["result_unit"] == "percent"
    assert q07["checks"]["calculation_correctness"] is True
    assert len(q07["selected_evidence"]) == 2

    q08 = questions["Q08"]
    assert q08["overall_status"] == "PARTIAL"
    assert q08["actual_answer"]["result_unit"] == "percentage_points"
    assert q08["expected_answer"]["display"] == "16.47 percentage points"
    assert q08["checks"]["calculation_correctness"] is True
    assert len(q08["selected_evidence"]) == 4

    q13 = questions["Q13"]
    assert q13["overall_status"] == "PARTIAL"
    assert q13["actual_answer"]["result_unit"] == "percent"
    assert q13["actual_answer"]["metrics"] == {
        "current_conversion_percent": "87.93770581778265642151481888",
        "prior_conversion_percent": "94.38844086021505376344086022",
        "change_percentage_points": "-6.45073504243239734192604134",
    }
    assert q13["checks"]["calculation_correctness"] is True

    q11 = questions["Q11"]
    assert q11["overall_status"] == "PARTIAL"
    assert q11["actual_answer"]["result_unit"] == "percent"
    assert q11["expected_answer"]["share_dilution_percent"] == (
        "1.014050091631032376298106292"
    )
    assert q11["checks"]["reference_matrix_cases_pass"] is True
    assert len(q11["selected_evidence"]) == 1
    assert len(q13["selected_evidence"]) == 4

    q10 = questions["Q10"]
    assert q10["overall_status"] == "PARTIAL"
    assert q10["actual_answer"]["result_unit"] == "percent"
    assert q10["expected_answer"]["share_repurchase_amount"] == "33706000000"
    assert q10["expected_answer"]["prior_year_amount"] == "9533000000"
    assert q10["checks"]["reference_matrix_cases_pass"] is True
    assert len(q10["selected_evidence"]) == 2

    q12 = questions["Q12"]
    assert q12["overall_status"] == "PARTIAL"
    assert q12["actual_answer"]["largest_component"] == "Net income"
    assert q12["actual_answer"]["result_value"] == (
        "91.87288060811577394834041373"
    )
    assert q12["checks"]["reference_matrix_cases_pass"] is True
    assert q12["checks"]["signed_component_preserved"] is True
    assert "no live" in q12["failure_reason"].lower() or "live SEC" in q12["failure_reason"]

    q14 = questions["Q14"]
    assert q14["overall_status"] == "PARTIAL"
    assert q14["checks"]["reference_matrix_cases_pass"] is True
    assert len(q14["actual_answer"]) == 6
    assert q14["actual_answer"][-1]["cash_allocation_percent"] == (
        "106.6064476776519976319047021"
    )

    q15 = questions["Q15"]
    assert q15["overall_status"] == "PARTIAL"
    assert q15["checks"]["reference_matrix_cases_pass"] is True
    assert len(q15["actual_answer"]) == 6

    q06 = questions["Q06"]
    assert q06["overall_status"] == "PARTIAL"
    assert q06["checks"]["reference_matrix_cases_pass"] is True
    assert len(q06["actual_answer"]) == 6
    assert q06["actual_answer"][-1]["equity_change"] == "16783000000"

    q16 = questions["Q16"]
    assert q16["overall_status"] == "PARTIAL"
    assert q16["checks"]["reference_matrix_cases_pass"] is True
    assert len(q16["actual_answer"]) == 6
    assert all(item["excerpt"] for item in q16["actual_answer"])

    q09 = questions["Q09"]
    assert q09["overall_status"] == "PARTIAL"
    assert q09["actual_answer"]["result_unit"] == "percentage_points"
    assert q09["checks"]["matrix_cases_pass"] is True
    assert q09["narrative_evidence"]["source_url"].startswith("https://www.sec.gov/")

    for question_id in [
        f"Q{number:02d}"
        for number in range(2, 21)
        if number not in {3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16}
    ]:
        question = questions[question_id]
        assert question["overall_status"] == "UNSUPPORTED"
        assert question["retrieved_inputs"] == []
        assert question["actual_answer"]
        assert question["failure_reason"]
