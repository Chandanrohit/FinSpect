"""FinSpect Streamlit interface.

The UI calls the existing orchestration layer and displays its result.
It does not perform financial calculations or invent evidence.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
import requests
import streamlit as st

# Streamlit may execute this file without putting the src-layout package root
# on sys.path (for example, when launched with a global Python interpreter).
_SRC_ROOT = str(Path(__file__).resolve().parents[1])
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from finspect.orchestrator import run_query
from finspect.gnani_voice import (
    GnaniAPIError,
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
    :root { --ink:#17243a; --muted:#62718a; --line:#e1e8f1; --blue:#2457d6; --teal:#0d8276; }
    .stApp {background:linear-gradient(180deg,#eaf2ff 0%,#f3f7fd 360px,#f8fafc 100%); color:var(--ink);}
    .block-container {max-width:1180px; padding-top:1.5rem; padding-bottom:4rem;}
    [data-testid="stSidebar"] {background:#fff; border-right:1px solid var(--line);}
    [data-testid="stSidebarContent"] {padding-top:1rem;}
    h1,h2,h3 {color:var(--ink); letter-spacing:-.025em;}
    [data-testid="stCaptionContainer"] {color:var(--muted);}
    div[data-testid="stForm"] {background:#fff; padding:1.25rem 1.4rem 1.35rem; border:1px solid var(--line); border-radius:18px; box-shadow:0 8px 26px rgba(23,36,58,.045);}
    div[data-testid="stMetric"] {background:#fff; border:1px solid var(--line); padding:1rem; border-radius:14px;}
    div.stButton > button, div.stFormSubmitButton > button {border-radius:11px; font-weight:650; min-height:2.8rem;}
    div.stFormSubmitButton > button[kind="primary"] {background:var(--blue); border-color:var(--blue);}
    [data-testid="stExpander"] {background:rgba(255,255,255,.78); border:1px solid var(--line); border-radius:13px;}
    .fs-kicker {color:var(--blue); font-size:.78rem; font-weight:750; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.45rem;}
    .fs-lede {max-width:760px; color:#52627b; font-size:1.05rem; line-height:1.6;}
    .fs-status {display:inline-block; background:#e9f5f2; color:#087367; border:1px solid #cce8e1; border-radius:999px; padding:.35rem .7rem; font-size:.78rem; font-weight:650;}
    .fs-card {background:#fff; border:1px solid var(--line); border-radius:16px; padding:1rem 1.1rem; min-height:92px; box-shadow:0 5px 18px rgba(23,36,58,.035);}
    .fs-card-label {color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700;}
    .fs-card-value {color:var(--ink); font-size:1rem; font-weight:650; margin-top:.35rem;}
    .fs-chart-card {background:linear-gradient(145deg,#fff 15%,#eef5ff 100%); border:1px solid #dce7f7; border-radius:18px; padding:1rem 1rem .75rem; box-shadow:0 10px 30px rgba(36,87,214,.08);}
    .fs-chart-title {color:var(--ink); font-size:.95rem; font-weight:700;}
    .fs-chart-subtitle {color:var(--muted); font-size:.78rem; margin-top:.15rem;}
    .fs-chart-note {color:#7b879a; font-size:.68rem; margin-top:.35rem;}
    [data-testid="stDataFrame"] {border:1px solid var(--line); border-radius:12px; overflow:hidden;}
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


def _voice_backend_request(path: str, **kwargs: Any) -> requests.Response:
    """Call the local FastAPI process without moving Gnani credentials into Streamlit."""
    base_url = os.getenv("FINSPECT_VOICE_API_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        response = requests.post(
            f"{base_url}{path}",
            timeout=(5, 75),
            **kwargs,
        )
    except requests.Timeout:
        raise GnaniAPIError(
            "The local voice backend timed out. Confirm FastAPI is running, then retry.",
            category="backend_timeout",
        ) from None
    except requests.ConnectionError:
        raise GnaniAPIError(
            "The local voice backend is unavailable. Start FastAPI in a second terminal, then retry.",
            category="backend_unavailable",
        ) from None
    except requests.RequestException:
        raise GnaniAPIError(
            "The local voice backend request failed.", category="backend_request_error"
        ) from None

    if not response.ok:
        detail: Any = None
        try:
            detail = response.json().get("detail")
        except (ValueError, TypeError, AttributeError):
            pass
        if isinstance(detail, dict):
            raise GnaniAPIError(
                str(detail.get("message") or "Gnani voice request failed."),
                status_code=detail.get("upstream_status") or response.status_code,
                category=detail.get("category"),
                request_id=detail.get("request_id"),
            )
        if isinstance(detail, str):
            message = detail
        else:
            message = f"Local voice backend returned HTTP {response.status_code}."
        raise GnaniAPIError(message, status_code=response.status_code)
    return response


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
                with st.spinner("Generating a concise spoken summary with Gnani AI..."):
                    audio = _voice_backend_request(
                        "/api/voice/synthesize",
                        json={"text": summary},
                    ).content
                st.caption("Spoken summary")
                st.audio(audio, format="audio/wav")
            except GnaniAPIError as exc:
                st.warning(f"Speech playback is unavailable: {exc}")
                if exc.request_id:
                    st.caption(f"Gnani request ID: {exc.request_id}")
    except Exception as exc:
        st.error("FinSpect could not complete this query.")
        st.info(
            "Check that SEC_USER_AGENT is set, Ollama is running, and the "
            "question asks about a supported filing metric or period."
        )
        with st.expander("Technical details", expanded=False):
            st.code(f"{type(exc).__name__}: {exc}", language="text")


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

with st.sidebar:
    st.markdown("## FinSpect")
    st.caption("SEC filing research")
    st.markdown(
        "Ask a company question, inspect the reporting periods, and open the "
        "filing sources behind the answer."
    )
    st.divider()
    st.divider()
    st.markdown("**Research workflow**")
    st.markdown("1. Ask a question\n2. Check periods and units\n3. Open SEC sources")
    st.caption("Prototype · verify important results against the cited filing.")

if "question" not in st.session_state:
    st.session_state.question = ""

hero_copy, hero_chart = st.columns([1.65, 1], gap="large", vertical_alignment="center")
with hero_copy:
    st.markdown('<div class="fs-kicker">SEC filing research · investor workflow</div>', unsafe_allow_html=True)
    st.title("Research a public company")
    st.markdown(
        '<div class="fs-lede">Ask about a US-listed company. FinSpect checks the filing, '
        'period, and units before calculating—and shows the evidence behind the result.</div>',
        unsafe_allow_html=True,
    )
with hero_chart:
    hero_chart.markdown(
        """
        <div class="fs-chart-card">
          <div class="fs-chart-title">Financial research, grounded in filings</div>
          <div class="fs-chart-subtitle">Evidence → period checks → clear results</div>
          <svg viewBox="0 0 380 150" role="img" aria-label="Decorative finance chart illustration; no live market data" style="width:100%;height:auto;margin-top:12px">
            <defs>
              <linearGradient id="fsArea" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#4f83f1" stop-opacity=".24"/><stop offset="1" stop-color="#4f83f1" stop-opacity="0"/></linearGradient>
            </defs>
            <path d="M18 24H365M18 62H365M18 100H365M18 138H365" stroke="#dce6f4" stroke-width="1"/>
            <g stroke-linecap="round">
              <path d="M48 89V116M48 97V108" stroke="#31a38e" stroke-width="5"/><path d="M94 70V103M94 77V95" stroke="#31a38e" stroke-width="5"/>
              <path d="M140 82V119M140 91V111" stroke="#ed8b73" stroke-width="5"/><path d="M186 52V91M186 61V80" stroke="#31a38e" stroke-width="5"/>
              <path d="M232 59V94M232 67V85" stroke="#31a38e" stroke-width="5"/><path d="M278 34V76M278 43V66" stroke="#31a38e" stroke-width="5"/>
              <path d="M324 43V82M324 51V71" stroke="#ed8b73" stroke-width="5"/>
            </g>
            <path d="M20 112C55 105 66 92 94 88S130 97 140 100 174 69 186 70 218 77 232 73 264 49 278 52 309 58 324 55 350 39 364 33V145H20Z" fill="url(#fsArea)"/>
            <path d="M20 112C55 105 66 92 94 88S130 97 140 100 174 69 186 70 218 77 232 73 264 49 278 52 309 58 324 55 350 39 364 33" fill="none" stroke="#315fd4" stroke-width="3" stroke-linecap="round"/>
            <circle cx="364" cy="33" r="4.5" fill="#315fd4" stroke="#fff" stroke-width="2"/>
          </svg>
          <div class="fs-chart-note">Illustrative finance graphic · not live market data</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
st.write("")
status_cols = st.columns(3)
for col, label, value in zip(
    status_cols,
    ("Primary source", "Question planning", "Answer style"),
    ("SEC filings", "Local Ollama model", "Evidence first"),
    strict=True,
):
    col.markdown(
        f'<div class="fs-card"><div class="fs-card-label">{label}</div>'
        f'<div class="fs-card-value">{value}</div></div>',
        unsafe_allow_html=True,
    )

st.write("")
st.subheader("Start with a question")
st.caption("Use a company name and fiscal period. Examples below are ready to load.")

example_cols = st.columns(len(EXAMPLES))
for index, (label, example) in enumerate(EXAMPLES):
    with example_cols[index]:
        if st.button(label, use_container_width=True, key=f"example_{index}"):
            st.session_state.question = example

with st.expander("Ask by voice with Gnani AI"):
    st.caption(
        "The recorded clip is sent to Gnani AI for transcription. Review the "
        "transcribed question before FinSpect retrieves filing data. The "
        "spoken response is a concise English summary; exact figures and SEC "
        "evidence stay in the written answer."
    )
    st.caption(
        "Voice is optional. Configure the shared key in the local "
        "`.streamlit/secrets.toml` file; credentials are never entered on this dashboard."
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
    recorded_audio = st.audio_input(
        "Record a question (maximum 30 seconds)",
        sample_rate=16000,
        key="voice_recording",
    )
    st.caption(
        "Microphone access requires localhost or HTTPS. A plain HTTP Network URL may open the app but the browser will block recording."
    )
    if st.button(
        "Transcribe with Gnani AI",
        disabled=recorded_audio is None,
        key="transcribe_voice_question",
    ):
        st.session_state["voice_transcript"] = ""
        try:
            with st.spinner("Transcribing with Gnani Prisma v3..."):
                transcript_response = _voice_backend_request(
                    "/api/voice/transcribe",
                    data={"language_code": voice_languages[voice_language]},
                    files={
                        "audio_file": (
                            getattr(recorded_audio, "name", "question.wav"),
                            recorded_audio.getvalue(),
                            getattr(recorded_audio, "type", "audio/wav"),
                        )
                    },
                )
                try:
                    payload = transcript_response.json()
                except (ValueError, TypeError):
                    raise GnaniAPIError(
                        "The local voice backend returned invalid JSON.",
                        category="invalid_backend_response",
                    ) from None
                transcript = payload.get("transcript") if isinstance(payload, dict) else None
                if not isinstance(transcript, str) or not transcript.strip():
                    raise GnaniAPIError(
                        "The local voice backend returned an empty or invalid transcript.",
                        category="invalid_backend_response",
                    )
            st.session_state["voice_transcript"] = transcript.strip()
            st.session_state["voice_transcription_empty"] = False
        except (GnaniAPIError, ValueError) as exc:
            st.warning(f"Voice transcription is unavailable: {exc}")
            if isinstance(exc, GnaniAPIError):
                diagnostics = []
                if exc.status_code is not None:
                    diagnostics.append(f"HTTP {exc.status_code}")
                if exc.category:
                    diagnostics.append(f"code {exc.category}")
                if exc.request_id:
                    diagnostics.append(f"request ID {exc.request_id}")
                if diagnostics:
                    st.caption("Gnani diagnostic: " + " · ".join(diagnostics))
            st.session_state["voice_transcription_empty"] = (
                isinstance(exc, GnaniAPIError) and exc.category == "empty_transcript"
            )

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
    elif st.session_state.get("voice_transcription_empty"):
        st.info("Gnani returned no speech. Record a clear question and try again.")

with st.form("research_form"):
    question = st.text_area(
        "Your question",
        key="question",
        height=110,
        placeholder=(
        "Example: Calculate NVIDIA's revenue growth from FY2024 to FY2025."
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
