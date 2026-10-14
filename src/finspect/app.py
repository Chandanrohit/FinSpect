"""FinSpect Streamlit interface.

The UI calls the existing orchestration layer and displays its result.
It does not perform financial calculations or invent evidence.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

import streamlit as st

from orchestrator import run_query


st.set_page_config(
    page_title="FinSpect | Financial Research",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def to_json_safe(value: Any) -> Any:
    """Convert pipeline objects into values Streamlit can display."""
    if is_dataclass(value) and not isinstance(value, type):
        return to_json_safe(asdict(value))

    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(item) for item in value]

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, Enum):
        return value.value

    if hasattr(value, "model_dump"):
        return to_json_safe(value.model_dump(mode="json"))

    if hasattr(value, "__dict__"):
        return to_json_safe(vars(value))

    return value


def display_result(result: Any) -> None:
    """Render either the dictionary adapter or a PipelineResult."""
    if isinstance(result, dict):
        answer = result.get("answer")
        details = {k: v for k, v in result.items() if k != "answer"}
    else:
        answer = getattr(result, "answer", None)
        details = {
            "plan": getattr(result, "plan", None),
            "facts": getattr(result, "facts", ()),
        }

    if answer is None:
        st.warning("The pipeline returned no answer.")
    elif isinstance(answer, str):
        st.markdown(answer)
    else:
        # Answer is a structured object in the current pipeline.
        st.json(to_json_safe(answer))

    with st.expander("Inspect query plan, evidence, and pipeline details"):
        st.json(to_json_safe(details))


st.title("📊 FinSpect")
st.caption(
    "Evidence-grounded financial research using SEC company filings."
)

with st.sidebar:
    st.header("About FinSpect")
    st.markdown(
        """
        **Research workflow**

        1. Interpret your question with the LLM planner.
        2. Normalize the company and reporting period.
        3. Retrieve facts from SEC filings.
        4. Validate the evidence and calculate deterministically.
        5. Present the answer and its sources.
        """
    )

    st.divider()
    st.info(
        "Current pipeline support is limited to the operations "
        "implemented in the orchestrator. Unsupported questions "
        "should receive an explicit limitation."
    )
    st.caption(
        "FinSpect is a research tool, not personalized investment advice."
    )

EXAMPLES = [
    "Calculate NVIDIA's revenue growth from FY2024 to FY2025.",
    "Calculate NVIDIA's revenue growth from FY2023 to FY2024.",
    "What was NVIDIA's revenue growth from FY2024 to FY2025?",
]

if "question" not in st.session_state:
    st.session_state.question = ""

st.subheader("Ask a financial research question")

example_cols = st.columns(len(EXAMPLES))
for index, example in enumerate(EXAMPLES):
    if example_cols[index].button(
        f"Example {index + 1}",
        use_container_width=True,
    ):
        st.session_state.question = example

with st.form("research_form"):
    question = st.text_area(
        "Your question",
        key="question",
        height=120,
        placeholder=(
            "Example: Calculate NVIDIA's revenue growth "
            "from FY2024 to FY2025."
        ),
    )
    submitted = st.form_submit_button(
        "Research question",
        type="primary",
        use_container_width=True,
    )

if submitted:
    cleaned_question = question.strip()

    if not cleaned_question:
        st.warning("Please enter a question.")
    else:
        try:
            with st.spinner(
                "Planning the question and retrieving SEC evidence..."
            ):
                result = run_query(cleaned_question)

            st.divider()
            st.subheader("Research result")
            display_result(result)

        except Exception as exc:
            st.error("FinSpect could not complete this query.")
            st.info(
                " The Pipeline encountered an error."
                "Check the developer diagnostics below." 
            )
            with st.expander("Developer diagnostics", expanded=True):
                st.code(
                    f"{type(exc).__name__}: {exc}",
                    language="text",
                 )
