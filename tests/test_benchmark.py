
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from finspect.calculator import (
    BENCHMARK_FORMULAS,
    NON_CALCULATION_BENCHMARK_IDS,
)
from finspect.schema import load_benchmark


ROOT = Path(__file__).resolve().parents[1]


def find_benchmark() -> Path:
    """Find the benchmark JSON without hardcoding a versioned filename."""
    configured = os.getenv("FINSPECT_BENCHMARK")

    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise FileNotFoundError(
                f"FINSPECT_BENCHMARK does not exist: {path}"
            )
        return path

    candidates = [
        ROOT / "data" / "finspect_benchmark_v02_clean(4).json",
        ROOT / "data" / "finspect_benchmark_v02_clean(2).json",
    ]

    candidates.extend(
        path for path in (ROOT / "data").glob("*.json")
        if "benchmark" in path.name.lower()
    )

    for path in candidates:
        if path.is_file():
            return path

    raise FileNotFoundError(
        "Could not find benchmark JSON in the data folder. "
        "Set FINSPECT_BENCHMARK to its path."
    )


@pytest.fixture(scope="module")
def benchmark():
    path = find_benchmark()
    return load_benchmark(path)


def test_benchmark_has_twenty_unique_questions(benchmark):
    questions = benchmark.question_map()

    assert len(questions) == 20
    assert len(questions) == len(set(questions))
    assert {f"Q{i:02d}" for i in range(1, 21)} == set(questions)


def test_every_question_has_required_metadata(benchmark):
    for question in benchmark.question_map().values():
        assert question.category.strip()
        assert question.type.strip()
        assert question.question_template.strip()
        assert question.primary_test.strip()
        assert question.track in {
            "core_calculation",
            "advanced_filing_calculation",
            "evidence_disclosure",
        }


def test_calculation_questions_have_registered_handlers(benchmark):
    """Check calculator registration, not end-to-end correctness."""
    questions = benchmark.question_map()

    for question_id in BENCHMARK_FORMULAS:
        assert question_id in questions, (
            f"Calculator registers {question_id}, "
            "but the benchmark has no matching question."
        )

    for question_id in NON_CALCULATION_BENCHMARK_IDS:
        assert question_id in questions


def test_benchmark_question_ids_are_accounted_for(benchmark):
    """Every question must be classified as calculation or non-calculation."""
    questions = set(benchmark.question_map())
    registered = set(BENCHMARK_FORMULAS)
    non_calculation = set(NON_CALCULATION_BENCHMARK_IDS)

    assert registered.isdisjoint(non_calculation)
    assert registered | non_calculation == questions


def test_benchmark_file_is_valid_json():
    path = find_benchmark()
    parsed = json.loads(path.read_text(encoding="utf-8"))

    assert isinstance(parsed, dict)
    assert "layers" in parsed
    assert isinstance(parsed["layers"], list)


def main() -> int:
    """Print the current implementation coverage without claiming a pass."""
    benchmark = load_benchmark(find_benchmark())
    questions = benchmark.question_map()

    print("\nFinSpect benchmark implementation inventory")
    print("=" * 58)

    for question_id in sorted(questions):
        if question_id in BENCHMARK_FORMULAS:
            status = "CALCULATOR REGISTERED"
        elif question_id in NON_CALCULATION_BENCHMARK_IDS:
            status = "DISCLOSURE / RETRIEVAL REQUIRED"
        else:
            status = "NO HANDLER REGISTERED"

        print(f"{question_id}: {status}")

    print("\nImportant: registered does not mean end-to-end passed.")
    print("Real filing retrieval, validation, calculations, and evidence")
    print("still need integration tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
