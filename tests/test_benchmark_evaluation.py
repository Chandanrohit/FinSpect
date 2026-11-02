from finspect.benchmark_eval import evaluate_benchmark


def test_benchmark_report_records_fixture_and_unsupported_questions():
    report = evaluate_benchmark()

    assert report["question_count"] == 20
    assert report["aggregate_counts"] == {
        "PASS": 0,
        "PARTIAL": 5,
        "UNSUPPORTED": 15,
        "FAIL": 0,
    }
    assert report["accuracy_percentage"] is None
    assert report["live_sec_integration_tested"] is False
    assert report["live_query_planner_tested"] is False

    revenue_matrix = report["operation_reference_matrices"][0]
    assert revenue_matrix["question_id"] == "Q01"
    assert revenue_matrix["case_count"] == 6
    assert revenue_matrix["pass_count"] == 6
    assert revenue_matrix["fail_count"] == 0
    assert revenue_matrix["issuers"] == ["AAPL", "MSFT", "NVDA"]
    assert set(revenue_matrix["cases_per_issuer"].values()) == {2}

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
    assert len(q13["selected_evidence"]) == 4

    for question_id in [
        f"Q{number:02d}"
        for number in range(2, 21)
        if number not in {3, 5, 8, 13}
    ]:
        question = questions[question_id]
        assert question["overall_status"] == "UNSUPPORTED"
        assert question["retrieved_inputs"] == []
        assert question["actual_answer"]
        assert question["failure_reason"]
