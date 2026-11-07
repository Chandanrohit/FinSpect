"""FinSpect Streamlit interface

Voice-enabled financial research for US SEC filings built with the Gnani AI.

The UI calls the existing orchestration layer (``run_query``) and the local
FastAPI voice service (``finspect.voice_api:app``). It does not perform
financial calculations, invent evidence or store Gnani credentials in the
browser.

English only. The LLM (qwen2.5-coder:3b via Ollama) interprets the question
into a structured plan; the deterministic Python calculator performs all
arithmetic. One question per submission.

Backend interfaces used (verified from source, not invented):
    * finspect.orchestrator.run_query(question: str) -> dict
    * POST /api/voice/transcribe  (multipart: audio_file + language_code)
    * POST /api/voice/synthesize  (JSON: {"text": str})  -> audio/wav
    * GET  /health

Voice backend default: http://127.0.0.1:8000.
Override with FINSPECT_VOICE_API_URL.
"""

from __future__ import annotations

import html
import os
import sys
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import requests
import streamlit as st

_SRC_ROOT = str(Path(__file__).resolve().parents[1])
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from finspect.orchestrator import run_query
from finspect.gnani_voice import (
    GnaniAPIError,
    prepare_spoken_summary,
)


# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FinSpect | Voice-first financial research",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Cinematic dark theme
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    :root {
        --bg-0:#070b16;
        --bg-1:#0b1426;
        --surface:rgba(255,255,255,0.045);
        --surface-2:rgba(255,255,255,0.07);
        --border:rgba(255,255,255,0.09);
        --border-2:rgba(255,255,255,0.14);
        --ink:#f8fafc;
        --ink-2:#cbd5e1;
        --muted:#94a3b8;
        --cyan:#22d3ee;
        --cyan-soft:rgba(34,211,238,0.4);
        --blue:#3b82f6;
        --green:#10b981;
        --amber:#f59e0b;
        --red:#ef4444;
    }

    .stApp {
        background:
            radial-gradient(900px circle at 12% 8%, rgba(34,211,238,0.10), transparent 55%),
            radial-gradient(1100px circle at 88% 28%, rgba(59,130,246,0.10), transparent 55%),
            radial-gradient(700px circle at 50% 95%, rgba(34,211,238,0.05), transparent 55%),
            linear-gradient(180deg, var(--bg-0) 0%, var(--bg-1) 100%);
        background-attachment: fixed;
        color: var(--ink);
    }

    .block-container {
        max-width: 1200px;
        padding-top: 5.2rem;
        padding-bottom: 4rem;
    }

    .fs-blob {
        position: fixed; border-radius: 50%; filter: blur(90px);
        opacity: 0.28; z-index: 0; pointer-events: none;
        animation: fs-drift 22s ease-in-out infinite alternate;
    }
    .fs-blob--cyan { width: 460px; height: 460px; background: var(--cyan); top: -120px; left: -120px; }
    .fs-blob--blue { width: 560px; height: 560px; background: var(--blue); top: 30%; right: -180px; animation-delay: -7s; }
    .fs-blob--navy { width: 380px; height: 380px; background: #1e40af; bottom: -120px; left: 30%; animation-delay: -14s; opacity: 0.22; }
    @keyframes fs-drift {
        0%   { transform: translate(0,0) scale(1); }
        100% { transform: translate(70px,-50px) scale(1.12); }
    }
    .stApp > * { position: relative; z-index: 1; }

    h1,h2,h3,h4 { color: var(--ink) !important; letter-spacing: -0.025em; }

    /* ---- Input widget text — white box, black text, no focus color change ---- */
    div[data-testid="stTextArea"] textarea,
    div[data-testid="stTextInput"] input,
    div[data-testid="stNumberInput"] input {
        color: #000000 !important;
        caret-color: #000000 !important;
        background: #ffffff !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 8px;
    }
    div[data-testid="stTextArea"] textarea:focus,
    div[data-testid="stTextInput"] input:focus,
    div[data-testid="stNumberInput"] input:focus {
        color: #000000 !important;
        background: #ffffff !important;
        border-color: #94a3b8 !important;
    }
    div[data-testid="stTextArea"] textarea::placeholder,
    div[data-testid="stTextInput"] input::placeholder {
        color: #475569 !important;
        opacity: 1 !important;
    }
    div[data-testid="stTextArea"] label,
    div[data-testid="stTextInput"] label,
    div[data-testid="stSelectbox"] label,
    div[data-testid="stNumberInput"] label,
    div[data-testid="stCheckbox"] label,
    div[data-testid="stFileUploader"] label {
        color: var(--ink-2) !important;
        font-weight: 600;
    }
    div[data-testid="stSelectbox"] [data-baseweb="select"] > div {
        background: rgba(255,255,255,0.04) !important;
        border-color: var(--border) !important;
    }
    div[data-testid="stSelectbox"] [data-baseweb="select"] [data-baseweb="single-value"] {
        color: var(--ink) !important;
    }
    div[data-testid="stSelectbox"] [data-baseweb="select"] svg {
        color: var(--muted) !important; fill: var(--muted) !important;
    }
    [data-baseweb="menu"] { background: #0f1a2e !important; color: var(--ink) !important; }
    [data-baseweb="menu"] li { color: var(--ink) !important; }
    [data-baseweb="menu"] li:hover { background: rgba(34,211,238,0.10) !important; color: var(--cyan) !important; }
    div[data-testid="stCheckbox"] [data-baseweb="checkbox"] { border-color: var(--border-2) !important; }
    div[data-testid="stCheckbox"] [data-baseweb="checkbox"][aria-checked="true"] {
        background-color: var(--cyan) !important; border-color: var(--cyan) !important;
    }
    [data-testid="stCaptionContainer"] { color: var(--muted) !important; }
    div[data-testid="stMarkdownContainer"] p,
    div[data-testid="stMarkdownContainer"] li,
    div[data-testid="stMarkdownContainer"] span { color: var(--ink-2); }
    div[data-testid="stMarkdownContainer"] strong { color: var(--ink); }
    code, pre { color: var(--ink) !important; background: rgba(255,255,255,0.05) !important; border-radius: 6px; }
    [data-testid="stJson"] { color: var(--ink-2) !important; }
    [data-testid="stSpinner"] { color: var(--ink-2) !important; }
    [data-testid="stSpinner"] > div > div { color: var(--cyan) !important; }
    a { color: var(--cyan); }

    /* ---- Hero brand ---- */
    .fs-hero { text-align: center; padding: 0.6rem 0 0.4rem; }
    .fs-brand {
        font-size: 2.9rem; font-weight: 800; letter-spacing: -0.035em;
        background: linear-gradient(135deg,#f8fafc 0%,#22d3ee 55%,#3b82f6 100%);
        -webkit-background-clip: text; background-clip: text; color: transparent;
        margin: 0; line-height: 1.05;
        filter: drop-shadow(0 0 28px rgba(34,211,238,0.25));
    }
    .fs-brand-dot {
        display: inline-block; width: 11px; height: 11px; border-radius: 50%;
        background: var(--cyan);
        box-shadow: 0 0 14px var(--cyan-soft), 0 0 28px var(--cyan-soft);
        margin-right: 0.45rem; vertical-align: middle;
        animation: fs-blink 2.4s ease-in-out infinite;
    }
    @keyframes fs-blink { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
    .fs-tagline { color: var(--ink-2); font-size: 1.15rem; font-weight: 600; margin-top: 0.45rem; }
    .fs-description { color: var(--muted); font-size: 0.95rem; max-width: 680px; margin: 0.7rem auto 0; line-height: 1.6; }
    .fs-gnani-badge {
        display: inline-flex; align-items: center; gap: 0.4rem;
        background: rgba(34,211,238,0.08); border: 1px solid rgba(34,211,238,0.28);
        color: var(--cyan); border-radius: 999px; padding: 0.38rem 0.9rem;
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.07em;
        text-transform: uppercase; margin-top: 1.0rem;
    }

    /* ---- Stat cards ---- */
    .fs-stats { display: grid; grid-template-columns: repeat(3,1fr); gap: 0.85rem; margin: 1.6rem 0 0.4rem; }
    @media (max-width: 720px) { .fs-stats { grid-template-columns: repeat(1,1fr); } }
    .fs-stat {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: 14px; padding: 1rem 0.8rem; text-align: center;
        transition: transform 0.22s, border-color 0.22s, box-shadow 0.22s;
    }
    .fs-stat:hover { transform: translateY(-3px); border-color: rgba(34,211,238,0.35); box-shadow: 0 10px 28px rgba(34,211,238,0.10); }
    .fs-stat-num {
        font-size: 1.85rem; font-weight: 800; line-height: 1.05;
        background: linear-gradient(135deg,#22d3ee 0%,#3b82f6 100%);
        -webkit-background-clip: text; background-clip: text; color: transparent;
    }
    .fs-stat-num--text { font-size: 1.25rem; letter-spacing: 0.02em; }
    .fs-stat-label { color: var(--muted); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 600; margin-top: 0.3rem; }

    /* ---- Section heading ---- */
    .fs-section-h { display: flex; align-items: center; gap: 0.55rem; flex-wrap: wrap; color: var(--ink); font-size: 1.18rem; font-weight: 700; margin: 0 0 0.6rem; }
    .fs-section-h .fs-chip {
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase;
        color: var(--cyan); background: rgba(34,211,238,0.08);
        border: 1px solid rgba(34,211,238,0.22); border-radius: 999px; padding: 0.2rem 0.6rem;
    }

    /* ---- Waveform ---- */
    .fs-waveform { display: flex; align-items: center; justify-content: center; gap: 3px; height: 64px; margin: 0.4rem 0 0.2rem; }
    .fs-wave-bar {
        width: 3px; background: linear-gradient(180deg,var(--cyan) 0%,var(--blue) 100%);
        border-radius: 2px; height: 8px; opacity: 0.55;
        animation: fs-wave 1.4s ease-in-out infinite; box-shadow: 0 0 6px var(--cyan-soft);
    }
    @keyframes fs-wave { 0%,100% { height: 8px; opacity: 0.5; } 50% { height: 38px; opacity: 1; } }

    /* ---- Streamlit widget overrides ---- */
    div[data-testid="stForm"] {
        background: var(--surface); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
        border: 1px solid var(--border); border-radius: 18px; padding: 1.3rem 1.5rem 1.45rem;
        box-shadow: 0 10px 36px rgba(0,0,0,0.30);
    }
    div.stButton > button, div.stFormSubmitButton > button {
        border-radius: 11px; font-weight: 650; min-height: 2.6rem;
        background: var(--surface-2); border: 1px solid var(--border-2); color: var(--ink); transition: all 0.2s;
    }
    div.stButton > button:hover { border-color: rgba(34,211,238,0.45); background: rgba(34,211,238,0.08); color: var(--cyan); }
    div.stFormSubmitButton > button[kind="primary"] {
        background: linear-gradient(135deg,var(--cyan) 0%,var(--blue) 100%);
        border: none; color: #06101f; font-weight: 750; box-shadow: 0 8px 24px rgba(34,211,238,0.32);
    }
    div.stFormSubmitButton > button[kind="primary"]:hover { background: linear-gradient(135deg,#67e8f9 0%,#60a5fa 100%); box-shadow: 0 10px 30px rgba(34,211,238,0.48); }

    div[data-testid="stTabs"] button[data-baseweb="tab"] { background: transparent; border-radius: 10px 10px 0 0; font-weight: 600; color: var(--muted); }
    div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] { color: var(--cyan); }
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"] { background-color: var(--cyan); height: 3px; }

    [data-testid="stExpander"] { background: var(--surface); border: 1px solid var(--border); border-radius: 13px; }
    [data-testid="stExpander"] p, [data-testid="stExpander"] li, [data-testid="stExpander"] span { color: var(--ink-2); }
    [data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }

    div[data-testid="stMetric"] { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 0.85rem 1rem; transition: border-color 0.2s; }
    div[data-testid="stMetric"]:hover { border-color: rgba(34,211,238,0.3); }
    [data-testid="stMetricLabel"] { color: var(--muted) !important; }
    [data-testid="stMetricValue"] { color: var(--ink) !important; font-weight: 700; }

    [data-testid="stAudioInput"] { background: rgba(34,211,238,0.04); border: 1px dashed rgba(34,211,238,0.3); border-radius: 12px; padding: 0.6rem; }

    /* ---- Result card ---- */
    .fs-result-card {
        background: linear-gradient(135deg,rgba(34,211,238,0.07) 0%,rgba(59,130,246,0.07) 100%);
        border: 1px solid rgba(34,211,238,0.22); border-left: 4px solid var(--cyan);
        border-radius: 14px; padding: 1.1rem 1.3rem; box-shadow: 0 10px 30px rgba(34,211,238,0.12);
        animation: fs-reveal 0.6s cubic-bezier(0.16,1,0.3,1);
    }
    @keyframes fs-reveal { 0% { opacity: 0; transform: translateY(18px); } 100% { opacity: 1; transform: translateY(0); } }
    .fs-result-label { color: var(--cyan); font-size: 0.72rem; font-weight: 700; letter-spacing: 0.11em; text-transform: uppercase; }
    .fs-result-text { color: var(--ink); font-size: 1.12rem; font-weight: 650; margin-top: 0.35rem; line-height: 1.5; }

    /* ---- Evidence grid ---- */
    .fs-evidence-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(230px,1fr)); gap: 0.8rem; margin-top: 0.6rem; }
    .fs-evidence-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 0.95rem 1.05rem; transition: border-color 0.22s, transform 0.22s, box-shadow 0.22s; }
    .fs-evidence-card:hover { border-color: rgba(34,211,238,0.32); transform: translateY(-2px); box-shadow: 0 8px 22px rgba(34,211,238,0.08); }
    .fs-evidence-label { color: var(--cyan); font-size: 0.7rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }
    .fs-evidence-value { color: var(--ink); font-size: 1.1rem; font-weight: 700; margin-top: 0.3rem; }
    .fs-evidence-unit { color: var(--muted); font-size: 0.82rem; font-weight: 500; }
    .fs-evidence-meta { color: var(--muted); font-size: 0.74rem; margin-top: 0.45rem; line-height: 1.45; }
    .fs-evidence-link { color: var(--cyan); font-size: 0.78rem; font-weight: 650; text-decoration: none; display: inline-block; margin-top: 0.55rem; }
    .fs-evidence-link:hover { text-decoration: underline; }

    /* ---- Status pills ---- */
    .fs-status { display: inline-block; background: rgba(34,211,238,0.08); color: var(--cyan); border: 1px solid rgba(34,211,238,0.22); border-radius: 999px; padding: 0.3rem 0.75rem; font-size: 0.73rem; font-weight: 650; }
    .fs-status--ok { background: rgba(16,185,129,0.10); color: var(--green); border: 1px solid rgba(16,185,129,0.28); }
    .fs-status--warn { background: rgba(245,158,11,0.10); color: var(--amber); border: 1px solid rgba(245,158,11,0.28); }
    .fs-status--err { background: rgba(239,68,68,0.10); color: var(--red); border: 1px solid rgba(239,68,68,0.28); }
    .fs-status-row { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; margin: 0.3rem 0 0.6rem; }

    .fs-hint-box { background: rgba(34,211,238,0.05); border: 1px solid rgba(34,211,238,0.18); border-radius: 10px; padding: 0.6rem 0.9rem; color: var(--ink-2); font-size: 0.85rem; line-height: 1.5; margin: 0.4rem 0 0.6rem; }
    .fs-hint-box strong { color: var(--cyan); }

    [data-testid="stSidebar"] { background: var(--bg-1); border-right: 1px solid var(--border); }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="fs-blob fs-blob--cyan"></div>
    <div class="fs-blob fs-blob--blue"></div>
    <div class="fs-blob fs-blob--navy"></div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _voice_backend_url() -> str:
    """Local FastAPI voice service URL. Default: http://127.0.0.1:8000."""
    return os.getenv("FINSPECT_VOICE_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _voice_backend_request(path: str, **kwargs: Any) -> requests.Response:
    """Call the local FastAPI process; surface sanitized errors only."""
    base_url = _voice_backend_url()
    try:
        response = requests.post(f"{base_url}{path}", timeout=(5, 75), **kwargs)
    except requests.Timeout:
        raise GnaniAPIError(
            "The local voice backend timed out. Confirm FastAPI is running, then retry.",
            category="backend_timeout",
        ) from None
    except requests.ConnectionError:
        raise GnaniAPIError(
            f"The local voice backend at {base_url} is unavailable. "
            "Start FastAPI in a second terminal "
            "(python -m uvicorn finspect.voice_api:app --host 127.0.0.1 --port 8000), "
            "then retry.",
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


# ---------------------------------------------------------------------------
# Voice transcription
# ---------------------------------------------------------------------------

# English only. Gnani STT language code for English (India).
VOICE_LANGUAGES = {
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


def _transcribe_audio(
    audio_bytes: bytes, filename: str, mime: str, language_code: str
) -> str:
    """Send real WAV bytes to the real FastAPI /api/voice/transcribe endpoint."""
    if not audio_bytes:
        raise GnaniAPIError(
            "No audio was captured. Record or upload a non-empty WAV clip.",
            category="empty_audio",
        )
    response = _voice_backend_request(
        "/api/voice/transcribe",
        data={"language_code": language_code},
        files={"audio_file": (filename, audio_bytes, mime)},
    )
    try:
        payload = response.json()
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
    return transcript.strip()


def _render_gnani_diagnostics(exc: GnaniAPIError) -> None:
    diagnostics = []
    if exc.status_code is not None:
        diagnostics.append(f"HTTP {exc.status_code}")
    if exc.category:
        diagnostics.append(f"code {exc.category}")
    if exc.request_id:
        diagnostics.append(f"request ID {exc.request_id}")
    if diagnostics:
        st.caption("Gnani diagnostic: " + " · ".join(diagnostics))


def _check_voice_backend() -> dict[str, Any]:
    """Quick GET /health probe of the local FastAPI voice service."""
    base_url = _voice_backend_url()
    try:
        response = requests.get(f"{base_url}/health", timeout=2)
    except requests.RequestException as exc:
        return {"reachable": False, "gnani_configured": False, "url": base_url, "error": type(exc).__name__}
    if not response.ok:
        return {"reachable": False, "gnani_configured": False, "url": base_url, "error": f"HTTP {response.status_code}"}
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return {"reachable": False, "gnani_configured": False, "url": base_url, "error": "invalid JSON"}
    return {"reachable": True, "gnani_configured": bool(payload.get("gnani_configured")), "url": base_url, "error": None}


def _render_voice_backend_status() -> None:
    if "voice_backend_status" not in st.session_state:
        st.session_state["voice_backend_status"] = _check_voice_backend()
    status = st.session_state["voice_backend_status"]
    if status["reachable"]:
        if status["gnani_configured"]:
            pill_class = "fs-status--ok"
            pill_text = f"● Voice backend ready · Gnani configured · {status['url']}"
        else:
            pill_class = "fs-status--warn"
            pill_text = f"● Voice backend ready · Gnani key not set · {status['url']}"
    else:
        pill_class = "fs-status--err"
        pill_text = f"● Voice backend offline · {status['url']} ({status.get('error') or 'unreachable'})"
    st.markdown(f'<div class="fs-status-row"><span class="fs-status {pill_class}">{pill_text}</span></div>', unsafe_allow_html=True)
    if not status["reachable"]:
        st.caption("Start the voice service: python -m uvicorn finspect.voice_api:app --host 127.0.0.1 --port 8000")
    cols = st.columns([1, 6])
    with cols[0]:
        if st.button("Recheck", key="recheck_voice_backend", use_container_width=True):
            st.session_state["voice_backend_status"] = _check_voice_backend()
            st.rerun()


def _waveform_html(n_bars: int = 36) -> str:
    bars = "".join(f'<div class="fs-wave-bar" style="animation-delay:{i * 0.055}s"></div>' for i in range(n_bars))
    return f'<div class="fs-waveform" aria-hidden="true">{bars}</div>'


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def _classify_error(exc: Exception) -> dict[str, str]:
    """Map a pipeline exception to a specific, actionable user message."""
    msg = str(exc)
    exc_type = type(exc).__name__
    lower = (msg + " " + exc_type).lower()

    if "sec_user_agent" in lower or "user-agent is required" in lower:
        return {"title": "SEC_USER_AGENT is not set in this terminal",
                "message": "Set it in the Streamlit terminal (Terminal 3), then restart Streamlit:\n  $env:SEC_USER_AGENT = \"FinSpect Student Developer your-email@example.com\"",
                "severity": "config"}
    if "ollama" in lower or "11434" in lower or "connection refused" in lower and "localhost" in lower:
        return {"title": "Ollama is not reachable",
                "message": "Start Ollama in Terminal 1: ollama serve\nThen verify: Invoke-RestMethod http://127.0.0.1:11434/api/tags\nAlso run once if the model is missing: ollama pull qwen2.5-coder:3b",
                "severity": "config"}
    if "queryplanningerror" in lower or "planner" in lower:
        return {"title": "The planner could not interpret this question",
                "message": "Try rephrasing with a clear company name and fiscal period.\nSupported examples:\n  • Calculate NVIDIA's revenue growth from FY2024 to FY2025.\n  • How did Apple's operating margin change between FY2024 and FY2025?",
                "severity": "question"}
    if "factretrievalerror" in lower or "edgarapierror" in lower:
        return {"title": "SEC EDGAR retrieval failed",
                "message": "FinSpect could not retrieve the requested financial facts. Check your internet connection and SEC_USER_AGENT, then retry.",
                "severity": "retrieval"}
    if "filingretrievalerror" in lower:
        return {"title": "SEC filing retrieval failed",
                "message": "The requested SEC filing could not be retrieved. Retry in a few seconds.",
                "severity": "retrieval"}
    if "timeout" in lower or "timed out" in lower:
        return {"title": "A request timed out",
                "message": "The Ollama planner or SEC EDGAR took too long.\nRaise: $env:FINSPECT_OLLAMA_TIMEOUT = \"600\"\nOr retry with a simpler question.",
                "severity": "timeout"}
    if "connection" in lower and ("error" in lower or "refused" in lower):
        return {"title": "Network connection failed",
                "message": "Check that Ollama (Terminal 1) is running and your internet connection is up.",
                "severity": "network"}
    return {"title": "FinSpect could not complete this query",
            "message": "Check that SEC_USER_AGENT is set in the Streamlit terminal, Ollama is running, and the question asks about a supported filing metric or period.",
            "severity": "unknown"}


# ---------------------------------------------------------------------------
# Answer rendering
# ---------------------------------------------------------------------------

def _answer_fields(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        answer = result.get("answer") or {}
        if isinstance(answer, dict):
            return {
                "text": answer.get("text", "") or "",
                "formula_id": answer.get("formula_id"),
                "result_value": answer.get("result_value"),
                "result_unit": answer.get("result_unit"),
                "evidence": list(answer.get("evidence") or []),
                "limitations": list(answer.get("limitations") or []),
                "plan": result.get("plan"),
                "facts": list(result.get("facts") or []),
                "canonical_facts": list(result.get("canonical_facts") or []),
            }
    answer = getattr(result, "answer", None)
    return {
        "text": getattr(answer, "text", "") if answer else "",
        "formula_id": getattr(answer, "formula_id", None) if answer else None,
        "result_value": getattr(answer, "result_value", None) if answer else None,
        "result_unit": getattr(answer, "result_unit", None) if answer else None,
        "evidence": [to_json_safe(e) for e in (getattr(answer, "evidence", ()) if answer else ())],
        "limitations": list(getattr(answer, "limitations", ()) if answer else ()),
        "plan": getattr(result, "plan", None),
        "facts": [],
        "canonical_facts": [],
    }


def _render_interpretation(fields: dict[str, Any]) -> None:
    plan = fields.get("plan")
    facts = fields.get("facts") or []
    canonical_facts = fields.get("canonical_facts") or []
    if plan is None and not facts and not canonical_facts:
        return
    with st.expander("How FinSpect interpreted the question"):
        st.json(to_json_safe({"plan": plan, "facts": facts, "canonical_facts": canonical_facts}))


def _render_evidence_cards(evidence: list[Any]) -> None:
    items = []
    for item in evidence:
        if not isinstance(item, dict):
            item = to_json_safe(item)
        if not isinstance(item, dict):
            continue
        label = html.escape(str(item.get("label") or "—"))
        value = html.escape(str(item.get("value") or "—"))
        unit = html.escape(str(item.get("unit") or ""))
        period = html.escape(str(item.get("period") or ""))
        filing_date = html.escape(str(item.get("filing_date") or ""))
        accession = item.get("accession_number")
        source_url = item.get("source_url")
        meta_parts = [p for p in (period, f"filed {filing_date}" if filing_date else "") if p]
        if accession and not source_url:
            meta_parts.append(f"accession {html.escape(str(accession))}")
        meta_html = " · ".join(meta_parts)
        link_html = f'<a class="fs-evidence-link" href="{html.escape(str(source_url))}" target="_blank" rel="noopener">SEC filing →</a>' if source_url else ""
        items.append(f'<div class="fs-evidence-card"><div class="fs-evidence-label">{label}</div><div class="fs-evidence-value">{value} <span class="fs-evidence-unit">{unit}</span></div><div class="fs-evidence-meta">{meta_html}</div>{link_html}</div>')
    if not items:
        return
    st.markdown(f'<div class="fs-evidence-grid">{"".join(items)}</div>', unsafe_allow_html=True)


def _render_unsupported_hint() -> None:
    st.markdown(
        """
        <div class="fs-hint-box" style="border-color: rgba(245,158,11,0.25);">
          <strong>Try a supported question (one at a time):</strong><br/>
          • Calculate NVIDIA's revenue growth from FY2024 to FY2025.<br/>
          • How did Apple's operating margin change between FY2024 and FY2025?<br/>
          • Compare NVIDIA's cash conversion from FY2024 to FY2025.<br/>
          • Compare Microsoft's revenue growth between FY2024 and FY2025.
        </div>
        """,
        unsafe_allow_html=True,
    )


def display_result(result: Any, *, question: str = "") -> None:
    fields = _answer_fields(result)
    text = fields["text"] or ""
    formula_id = fields["formula_id"]
    result_value = fields["result_value"]
    result_unit = fields["result_unit"]
    evidence = fields["evidence"]
    limitations = fields["limitations"]

    if not text:
        st.warning("The pipeline returned no answer.")
        return

    if formula_id is None:
        st.info(text)
        if limitations:
            with st.expander("Why FinSpect could not answer this", expanded=True):
                for lim in limitations:
                    st.write(f"- {lim}")
        _render_unsupported_hint()
        _render_interpretation(fields)
        return

    result_line = next((line.removeprefix("Result: ").strip() for line in text.splitlines() if line.startswith("Result: ")), None)
    headline = html.escape(result_line or "See full calculation below.")
    st.markdown(f'<div class="fs-result-card"><div class="fs-result-label">Answer</div><div class="fs-result-text">{headline}</div></div>', unsafe_allow_html=True)

    calc_cols = st.columns(3)
    with calc_cols[0]: st.metric("Formula", formula_id or "—")
    with calc_cols[1]: st.metric("Result", result_value or "—")
    with calc_cols[2]: st.metric("Unit", result_unit or "—")

    with st.expander("Full calculation", expanded=True):
        st.markdown(text)

    if evidence:
        st.markdown(f'<div class="fs-section-h">SEC filing evidence <span class="fs-chip">{len(evidence)} source{"s" if len(evidence) != 1 else ""}</span></div>', unsafe_allow_html=True)
        _render_evidence_cards(evidence)

    if limitations:
        with st.expander("Limitations", expanded=False):
            for lim in limitations:
                st.write(f"- {lim}")

    _render_interpretation(fields)


# ---------------------------------------------------------------------------
# Research + TTS
# ---------------------------------------------------------------------------

def run_research(question: str, *, speak: bool = False) -> None:
    """Call the real orchestration layer. English only. One question at a time."""
    cleaned = (question or "").strip()
    if not cleaned:
        st.session_state["finspect_error"] = {"title": "Empty question", "message": "Please enter a financial question before submitting.", "detail": "", "severity": "empty"}
        st.session_state["finspect_result"] = None
        return

    try:
        with st.spinner("Planning the question and retrieving SEC evidence..."):
            result = run_query(cleaned)
        st.session_state["finspect_result"] = result
        st.session_state["finspect_question"] = cleaned
        st.session_state["finspect_error"] = None
    except Exception as exc:
        classified = _classify_error(exc)
        st.session_state["finspect_result"] = None
        st.session_state["finspect_error"] = {"title": classified["title"], "message": classified["message"], "detail": f"{type(exc).__name__}: {exc}", "severity": classified["severity"]}
        return

    if speak:
        _speak_answer(st.session_state["finspect_result"])


def _speak_answer(result: Any) -> None:
    """Generate and play a concise spoken summary via Gnani Timbre TTS (English)."""
    fields = _answer_fields(result)
    answer_text = fields["text"]
    result_unit = fields["result_unit"]
    if not answer_text:
        return
    summary = prepare_spoken_summary(answer_text, result_unit)
    try:
        with st.spinner("Generating spoken summary with Gnani Timbre v2.5..."):
            audio = _voice_backend_request("/api/voice/synthesize", json={"text": summary}).content
        st.caption("Listen to answer · Gnani Timbre v2.5 (English)")
        st.audio(audio, format="audio/wav")
    except GnaniAPIError as exc:
        st.warning(f"Speech playback is unavailable: {exc}")
        _render_gnani_diagnostics(exc)


# ---------------------------------------------------------------------------
# Page content
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="fs-hero">
      <div class="fs-brand"><span class="fs-brand-dot"></span>FinSpect</div>
      <div class="fs-tagline">Voice-first financial research</div>
      <div class="fs-description">
        Explore company financials, compare fiscal years, and understand
        performance using SEC filings. Ask a question in English — FinSpect
        interprets it with a local Qwen model, retrieves SEC EDGAR evidence,
        validates periods and units, calculates deterministically, and shows
        the evidence behind every answer.
      </div>
      <div class="fs-gnani-badge">⚡ Gnani Prisma v3 STT · Timbre v2.5 TTS</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="fs-stats">
      <div class="fs-stat"><div class="fs-stat-num fs-stat-num--text">SEC EDGAR</div><div class="fs-stat-label">Primary data source</div></div>
      <div class="fs-stat"><div class="fs-stat-num">NVDA · MSFT · AAPL</div><div class="fs-stat-label">Issuers covered</div></div>
      <div class="fs-stat"><div class="fs-stat-num">v3</div><div class="fs-stat-label">Gnani Prisma STT</div></div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.write("")

# --- Voice section ---
st.markdown('<div class="fs-section-h">Ask by voice <span class="fs-chip">Gnani Prisma v3</span></div>', unsafe_allow_html=True)
st.caption("Record a question or upload a WAV file (English, max 30 seconds). Audio goes to the local FastAPI service, transcribed by Gnani Prisma v3, then shown for review. Microphone capture requires localhost or HTTPS.")

_render_voice_backend_status()

with st.container():
    st.markdown(_waveform_html(36), unsafe_allow_html=True)

    voice_language = st.selectbox("Spoken language (for Gnani STT)", list(VOICE_LANGUAGES), key="voice_language", index=0)
    selected_language_code = VOICE_LANGUAGES[voice_language]

    voice_tabs = st.tabs(["🎙️ Record from microphone", "📁 Upload WAV file"])

    with voice_tabs[0]:
        recorded_audio = st.audio_input("Record a question (maximum 30 seconds)", sample_rate=16000, key="voice_recording")
        if recorded_audio is not None:
            st.caption(f"Captured: {getattr(recorded_audio, 'name', 'question.wav')}")
            st.audio(recorded_audio, format="audio/wav")
        if st.button("Transcribe recording with Gnani Prisma", disabled=recorded_audio is None, key="transcribe_recording"):
            st.session_state["voice_transcript"] = ""
            st.session_state["voice_transcription_error"] = None
            st.session_state["voice_transcription_empty"] = False
            try:
                with st.spinner("Transcribing with Gnani Prisma v3..."):
                    transcript = _transcribe_audio(recorded_audio.getvalue(), getattr(recorded_audio, "name", "question.wav"), getattr(recorded_audio, "type", "audio/wav"), selected_language_code)
                st.session_state["voice_transcript"] = transcript
            except GnaniAPIError as exc:
                st.session_state["voice_transcription_error"] = str(exc)
                st.session_state["voice_transcript"] = ""
                st.session_state["voice_transcription_empty"] = (exc.category == "empty_transcript")

    with voice_tabs[1]:
        uploaded_audio = st.file_uploader("Choose a WAV file", type=["wav"], key="voice_upload", accept_multiple_files=False)
        if uploaded_audio is not None:
            try: size_bytes = len(uploaded_audio.getvalue())
            except Exception: size_bytes = getattr(uploaded_audio, "size", 0) or 0
            st.caption(f"File: {uploaded_audio.name} · {size_bytes:,} bytes")
            st.audio(uploaded_audio, format="audio/wav")
        if st.button("Transcribe WAV file with Gnani Prisma", disabled=uploaded_audio is None, key="transcribe_upload"):
            st.session_state["voice_transcript"] = ""
            st.session_state["voice_transcription_error"] = None
            st.session_state["voice_transcription_empty"] = False
            try:
                with st.spinner("Transcribing with Gnani Prisma v3..."):
                    transcript = _transcribe_audio(uploaded_audio.getvalue(), uploaded_audio.name, getattr(uploaded_audio, "type", "audio/wav"), selected_language_code)
                st.session_state["voice_transcript"] = transcript
            except GnaniAPIError as exc:
                st.session_state["voice_transcription_error"] = str(exc)
                st.session_state["voice_transcript"] = ""
                st.session_state["voice_transcription_empty"] = (exc.category == "empty_transcript")
            except (ValueError, AttributeError) as exc:
                st.session_state["voice_transcription_error"] = f"The uploaded WAV file is invalid: {exc}"
                st.session_state["voice_transcript"] = ""

    if "voice_transcript" not in st.session_state: st.session_state["voice_transcript"] = ""
    if "voice_transcription_error" not in st.session_state: st.session_state["voice_transcription_error"] = None
    if "voice_transcription_empty" not in st.session_state: st.session_state["voice_transcription_empty"] = False

    if st.session_state["voice_transcription_error"]:
        st.error(f"Voice transcription is unavailable: {st.session_state['voice_transcription_error']}")
    elif st.session_state.get("voice_transcription_empty"):
        st.info("Gnani returned no speech. Record or upload a clearer clip and try again.")
    elif st.session_state["voice_transcript"]:
        st.text_area("Recognized question (edit before running if needed)", key="voice_transcript", height=90)
        speak_after = st.checkbox("Also speak the answer (Gnani Timbre v2.5 TTS)", value=True, key="voice_speak_after")
        if st.button("Research recognized question", type="primary"):
            transcript_value = st.session_state["voice_transcript"] or ""
            run_research(transcript_value, speak=speak_after)

st.write("")
st.divider()

# --- Text input ---
st.markdown('<div class="fs-section-h">Ask by text <span class="fs-chip">SEC EDGAR · Ollama planner</span></div>', unsafe_allow_html=True)
st.caption("Type a financial question in English. Use a company name and a fiscal period. One question at a time. Click an example to load it — it will not submit automatically.")
st.caption("Supported question types: annual revenue growth, operating margin change, cash conversion, segment/equity/commitments for NVDA · MSFT · AAPL across FY2024–FY2025.")

EXAMPLES = [
    ("Microsoft · Revenue growth", "Compare Microsoft's revenue growth between FY2024 and FY2025."),
    ("Apple · Operating Margin", "How did Apple's operating margin change from FY2024 and FY2025?"),
    ("NVIDIA · Currency Risk", "What are currency exchange risk in NVIDIA business in FY2025?"),
    ("Amazon · Revenue growth", "Calculate Amazon's revenue growth from FY2023 to FY2025."),
]

example_cols = st.columns(len(EXAMPLES))
for index, (label, example) in enumerate(EXAMPLES):
    with example_cols[index]:
        if st.button(label, use_container_width=True, key=f"example_{index}"):
            st.session_state["question"] = example

st.write("")

if "question" not in st.session_state: st.session_state["question"] = ""
if "finspect_result" not in st.session_state: st.session_state["finspect_result"] = None
if "finspect_error" not in st.session_state: st.session_state["finspect_error"] = None
if "finspect_question" not in st.session_state: st.session_state["finspect_question"] = ""

with st.form("research_form", clear_on_submit=False):
    question_value = st.text_area("Your question", key="question", height=110, placeholder="Example: Compare Microsoft's revenue growth between FY2024 and FY2025.")
    submitted = st.form_submit_button("Find answer in SEC filings", type="primary", use_container_width=True)

if submitted:
    run_research(question_value)

st.write("")
st.divider()

# --- Results ---
st.markdown('<div class="fs-section-h">Research result</div>', unsafe_allow_html=True)

if st.session_state.get("finspect_error"):
    err = st.session_state["finspect_error"]
    st.error(err["title"])
    if err.get("message"): st.info(err["message"])
    if err.get("detail"):
        with st.expander("Technical details", expanded=True):
            st.code(err["detail"], language="text")

if st.session_state.get("finspect_result") is not None:
    display_result(st.session_state["finspect_result"], question=st.session_state.get("finspect_question", ""))
elif not st.session_state.get("finspect_error"):
    st.caption("Ready. Type a question above and select Find answer in SEC filings.")
