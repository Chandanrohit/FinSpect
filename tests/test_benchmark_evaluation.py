from finspect.benchmark_eval import evaluate_benchmark


def test_benchmark_report_records_fixture_and_unsupported_questions():
    report = evaluate_benchmark()

    assert report["question_count"] == 20
    assert report["aggregate_counts"] == {
        "PASS": 0,
        "PARTIAL": 1,
        "UNSUPPORTED": 19,
        "FAIL": 0,
    }
    assert report["accuracy_percentage"] is None
    assert report["live_sec_integration_tested"] is False
    assert report["live_query_planner_tested"] is False

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

    for question_id in [f"Q{number:02d}" for number in range(2, 21)]:
        question = questions[question_id]
        assert question["overall_status"] == "UNSUPPORTED"
        assert question["retrieved_inputs"] == []
        assert question["actual_answer"]
        assert question["failure_reason"]
