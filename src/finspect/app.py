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

from finspect.orchestrator import run_query
from finspect.gnani_voice import (
    GnaniAPIError,
    GnaniVoiceClient,
    gnani_api_key,
    prepare_spoken_summary,
)


st.set_page_config(
    page_title="FinSpect | Financial Research",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1120px; padding-top: 2rem; padding-bottom: 3rem;}
    [data-testid="stAppViewContainer"] {background: #f7f8fa;}
    [data-testid="stSidebar"] {background: #ffffff;}
    div[data-testid="stForm"] {background: #ffffff; padding: 1rem 1.2rem 1.2rem; border: 1px solid #e4e8ef; border-radius: 14px;}
    div[data-testid="stMetric"] {background: #ffffff; border: 1px solid #e4e8ef; padding: 1rem; border-radius: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
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
    """Render the answer and expose structured evidence when available."""

    if isinstance(result, dict):
        answer = result.get("answer")
        details = {
            key: value
            for key, value in result.items()
            if key != "answer"
        }
    else:
        answer = getattr(result, "answer", None)
        details = {
            "plan": getattr(result, "plan", None),
            "facts": getattr(result, "facts", ()),
            "canonical_facts": getattr(result, "canonical_facts", ()),
        }

    if answer is None:
        st.warning("The pipeline returned no answer.")

    elif isinstance(answer, str):
        st.markdown(answer)

    elif isinstance(answer, dict) and isinstance(
        answer.get("text"), str
    ):
        st.markdown(answer["text"])

        limitations = answer.get("limitations") or []
        if limitations:
            st.warning("Limitations")
            for limitation in limitations:
                st.write(f"- {limitation}")

        evidence = answer.get("evidence") or []
        if evidence:
            with st.expander(
                f"Sources and filing evidence ({len(evidence)})",
                expanded=True,
            ):
                st.dataframe(evidence, use_container_width=True, hide_index=True)

    elif hasattr(answer, "text"):
        st.markdown(answer.text)

        limitations = getattr(answer, "limitations", ())
        if limitations:
            st.warning("Limitations")
            for limitation in limitations:
                st.write(f"- {limitation}")

        evidence = getattr(answer, "evidence", ())
        if evidence:
            with st.expander(
                f"Sources and filing evidence ({len(evidence)})",
                expanded=True,
            ):
                st.dataframe(
                    [to_json_safe(item) for item in evidence],
                    use_container_width=True,
                    hide_index=True,
                )

    else:
        st.json(to_json_safe(answer))

    with st.expander("How FinSpect interpreted the question"):
        st.json(to_json_safe(details))


def configured_gnani_key() -> str | None:
    """Read server-side env/secrets without ever rendering the credential."""
    key = gnani_api_key()
    if key:
        return key
    try:
        return str(st.secrets.get("GNANI_API_KEY_ID", "")).strip() or None
    except Exception:
        return None


def research_and_display(question: str, *, speak: bool = False) -> None:
    try:
        with st.spinner("Planning the question and retrieving SEC evidence..."):
            result = run_query(question)
        st.divider()
        st.subheader("Research result")
        display_result(result)

        if speak:
            answer = (
                result.get("answer", {})
                if isinstance(result, dict)
                else getattr(result, "answer", None)
            )
            answer_text = (
                answer.get("text", "")
                if isinstance(answer, dict)
                else getattr(answer, "text", "")
            )
            answer_unit = (
                answer.get("result_unit")
                if isinstance(answer, dict)
                else getattr(answer, "result_unit", None)
            )
            summary = prepare_spoken_summary(
                str(answer_text),
                answer_unit,
            )
            try:
                api_key = configured_gnani_key()
                if not api_key:
                    st.info(
                        "Speech playback is disabled until GNANI_API_KEY_ID is "
                        "configured in the server environment or Streamlit secrets."
                    )
                    return
                with st.spinner("Generating a concise spoken summary with Gnani AI..."):
                    audio = GnaniVoiceClient(api_key).synthesize(summary)
                st.caption("Spoken summary")
                st.audio(audio, format="audio/wav")
            except GnaniAPIError as exc:
                st.warning(f"Speech playback is unavailable: {exc}")
    except Exception as exc:
        st.error("FinSpect could not complete this query.")
        st.exception(exc)
        st.info("Check the developer diagnostics below.")
        with st.expander("Developer diagnostics", expanded=True):
            st.code(f"{type(exc).__name__}: {exc}", language="text")


st.title("📊 FinSpect")
st.caption(
    "Understand a US public company using evidence from its SEC filings."
)

with st.sidebar:
    st.header("How to use FinSpect")
    st.markdown(
        """
        Ask about a company and reporting period. FinSpect retrieves filing
        data, checks the periods and units, and shows the sources behind its
        answer.
        """
    )

    st.divider()
    st.info(
        "Coverage is still expanding. If the filing data or calculation "
        "cannot be verified, FinSpect should say so instead of guessing."
    )
    st.caption(
        "For research and learning; not personalized investment advice."
    )

EXAMPLES = [
    (
        "Revenue growth · Microsoft",
        "Calculate Microsoft's revenue growth from FY2024 to FY2025.",
    ),
    (
        "Revenue growth · NVIDIA",
        "Calculate NVIDIA's revenue growth from FY2024 to FY2025.",
    ),
    (
        "Operating margin · NVIDIA",
        "How did NVIDIA's operating margin change from FY2024 to FY2025?",
    ),
    (
        "Cash conversion · NVIDIA",
        "Compare NVIDIA's cash conversion from FY2024 to FY2025.",
    ),
]

if "question" not in st.session_state:
    st.session_state.question = ""

st.subheader("What would you like to know?")
st.caption(
    "Name a US-listed company and, when relevant, the fiscal years to compare."
)

with st.expander("Ask by voice with Gnani AI"):
    st.caption(
        "The recorded clip is sent to Gnani AI for transcription. Review the "
        "transcribed question before FinSpect retrieves filing data. The "
        "spoken response is a concise English summary; exact figures and SEC "
        "evidence stay in the written answer."
    )
    voice_languages = {
        "English (India)": "en-IN",
        "Hindi": "hi-IN",
        "Tamil": "ta-IN",
        "Telugu": "te-IN",
        "Kannada": "kn-IN",
        "Malayalam": "ml-IN",
        "Marathi": "mr-IN",
        "Punjabi": "pa-IN",
        "Bengali": "bn-IN",
        "Gujarati": "gu-IN",
    }
    voice_language = st.selectbox(
        "Spoken language",
        list(voice_languages),
        key="voice_language",
    )
    recorded_audio = st.audio_input("Record a question (maximum 30 seconds)")
    if st.button(
        "Transcribe with Gnani AI",
        disabled=recorded_audio is None,
        key="transcribe_voice_question",
    ):
        api_key = configured_gnani_key()
        if not api_key:
            st.warning(
                "Set GNANI_API_KEY_ID in the server environment or "
                ".streamlit/secrets.toml to enable voice features."
            )
        else:
            try:
                with st.spinner("Transcribing with Gnani Prisma..."):
                    client = GnaniVoiceClient(api_key)
                    transcript = client.transcribe(
                        recorded_audio.getvalue(),
                        filename="question.wav",
                        language_code=voice_languages[voice_language],
                    )
                st.session_state["voice_transcript"] = transcript
            except (GnaniAPIError, ValueError) as exc:
                st.warning(f"Voice transcription is unavailable: {exc}")

    if "voice_transcript" not in st.session_state:
        st.session_state["voice_transcript"] = ""
    if st.session_state["voice_transcript"]:
        transcript = st.text_area(
            "Recognized question (edit before running if needed)",
            key="voice_transcript",
            height=90,
        )
        if st.button("Research recognized question", type="primary"):
            if transcript.strip():
                research_and_display(transcript.strip(), speak=True)
            else:
                st.warning("The recognized question is empty.")

st.caption("Try a supported example")
example_cols = st.columns(len(EXAMPLES))
for index, (label, example) in enumerate(EXAMPLES):
    if example_cols[index].button(
        label,
        use_container_width=True,
        key=f"example_{index}",
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
        "Find answer in SEC filings",
        type="primary",
        use_container_width=True,
    )

if submitted:
    cleaned_question = question.strip()

    if not cleaned_question:
        st.warning("Please enter a question.")
    else:
        research_and_display(cleaned_question)
