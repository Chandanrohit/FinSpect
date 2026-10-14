from finspect.llm_planner import (
    OllamaQueryPlanner,
    QueryPlanningError,
)


def main() -> None:
    planner = OllamaQueryPlanner(model="qwen3.5:4b")

    questions = [
        "Calculate NVIDIA's revenue growth from FY2024 to FY2025.",
        "Compare NVIDIA's accounts receivable growth with its revenue growth "
        "in FY2025.",
        "What major legal and regulatory risks did NVIDIA disclose in its "
        "FY2025 annual report?",
    ]

    for index, question in enumerate(questions, start=1):
        print(f"\n{'=' * 70}")
        print(f"TEST {index}: {question}")
        print("=" * 70)

        try:
            plan = planner.plan(question)
            print(plan.model_dump_json(indent=2))
        except (QueryPlanningError, ValueError) as exc:
            print(f"PLANNING FAILED: {exc}")


if __name__ == "__main__":
    main()
