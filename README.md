# FinSpect

FinSpect is an experimental financial research system. It uses a language model to interpret a question, SEC filing data to supply financial inputs, validation rules to reject incompatible facts, and deterministic Python calculations to produce an answer with its periods and sources.

> **Prototype status:** the current end-to-end calculation paths cover annual revenue growth, absolute annual revenue change, annual operating margin change, the net-income/operating-income change relationship, receivables/revenue growth comparison, and cash conversion comparison. The 20-question benchmark is not broadly supported. The current reproducible evaluation is **5 PARTIAL, 15 UNSUPPORTED**; see [`reports/benchmark-report.json`](reports/benchmark-report.json).

## Problem

Financial research requires finding the right company, concept, reporting period, and unit across filings before doing any calculation. A general-purpose LLM can mix periods, select the wrong metric, or invent values and citations. FinSpect separates those responsibilities:

**LLMs interpret questions. Validated filing data and deterministic code calculate.**

## Architecture

```mermaid
flowchart LR
    U[Research question] --> P[Ollama query planner]
    P --> N[Plan normalization]
    N --> C[Company and annual period resolution]
    C --> S[SEC EDGAR Company Facts]
    S --> V[Fact, unit, period, identity and provenance validation]
    V --> D[Decimal calculation]
    D --> A[Answer with formula, inputs and SEC evidence]
```

The Streamlit application calls the same orchestrator. It displays the structured plan and evidence returned by the pipeline; it does not calculate financial values in the UI.

## Current capabilities

- SEC company and filing metadata retrieval, plus XBRL Company Facts retrieval.
- Structured query plans validated with Pydantic.
- Deterministic company identity, annual period, unit, entity, and provenance checks.
- Q01 annual revenue growth and absolute annual revenue change in the orchestrator.
- Q03 annual operating margin change from SEC revenue and operating-income facts.
- Q05 the change in net income as a percentage of the change in operating income.
- Q08 annual receivables growth compared with revenue growth, with matching fiscal year ends.
- Q13 annual operating cash flow divided by net income for the current and comparable prior year, with both ratios and their percentage-point change.
- Optional Gnani Prisma v2.5 voice question input and Timbre v2.5 spoken result summary; the full written answer and SEC evidence remain visible.
- Decimal-based calculator functions for benchmark formulas; registration does **not** mean an operation is wired end to end.
- Evidence-bearing answers with reporting periods, filing dates, accession numbers, and SEC URLs.
- An initial filing parser and keyword-ranked narrative passage retriever. Disclosure answers are not enabled end to end.

## Setup

Use Python 3.11 or newer. From the repository root:

```powershell
python -m pip install -e ".[dev]"
```

Set a descriptive SEC User-Agent and start a local Ollama server with a model that supports structured JSON output:

```powershell
$env:SEC_USER_AGENT = "FinSpect/0.1 contact you@example.com"
$env:FINSPECT_OLLAMA_MODEL = "qwen2.5-coder:3b"
```

Run the app:

```powershell
python -m streamlit run src/finspect/app.py
```

The text workflow needs internet access for SEC requests and a reachable Ollama endpoint. `FINSPECT_OLLAMA_URL` can override the default local endpoint. Voice input/output additionally needs `GNANI_API_KEY_ID`; text research continues to work without it.

## Tests and benchmark evaluation

Run deterministic tests:

```powershell
python -m pytest -q
```

Generate the benchmark report:

```powershell
python -m finspect.benchmark_eval --output reports/benchmark-report.json
```

GitHub Actions runs the test suite on Python 3.11 and 3.12 for pushes and pull requests targeting `main`.

The checked-in NVIDIA FY2024/FY2025 snapshots provide repeatable Q01, Q03, Q05, Q08, and Q13 checks. Revenue inputs are USD 60.922 billion and USD 130.497 billion, producing **114.20%** growth. Operating income is USD 32.972 billion and USD 81.453 billion; the operating margin increased **8.30 percentage points**. Net income rose from USD 29.760 billion to USD 72.880 billion, equal to **88.94%** of the operating-income increase. Receivables are USD 9.999 billion and USD 23.065 billion; their growth exceeded revenue growth by **16.47 percentage points**. Operating cash flow was USD 28.090 billion and USD 64.089 billion; cash conversion was **94.39%** in FY2024 and **87.94%** in FY2025, a **6.45 percentage-point decrease**. Values and filing provenance are from the [FY2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/1045810/0001045810-24-000029-index.htm) and [FY2025 Form 10-K](https://www.sec.gov/Archives/edgar/data/1045810/0001045810-25-000023-index.htm).

The Q01, Q03, Q05, Q08, and Q13 reports are **PARTIAL** because they use checked-in filing snapshots and validated fixture plans; they do not run live SEC retrieval or the Ollama planner. Q02, Q04, Q06–Q07, Q09–Q12, and Q14–Q20 are **UNSUPPORTED** by the current retrieval-to-answer pipeline. No benchmark accuracy percentage is claimed. The benchmark itself contains generic question templates rather than fixed companies, filings, or reference answers.

## Demo

1. Install the project and set `SEC_USER_AGENT` and the Ollama model as shown above.
2. Start the application with Streamlit.
3. Ask one of: `Calculate NVIDIA's revenue growth from FY2024 to FY2025.`; `How did NVIDIA's operating margin change from FY2024 to FY2025?`; `How much of NVIDIA's operating income change from FY2024 to FY2025 was reflected in net income?`; `How did NVIDIA accounts receivable growth compare with revenue growth from FY2024 to FY2025?`; or `What percentage of NVIDIA net income was converted into operating cash flow during FY2025, and how did this compare with FY2024?`
4. Inspect the plan, result, periods, formula, and SEC evidence shown with the answer.
5. For deterministic offline checks of the four supported benchmark questions, regenerate the benchmark report.
6. To try voice input and spoken playback, set `GNANI_API_KEY_ID`; review the transcript before running the financial research query.

The live demo depends on Ollama and SEC availability. The benchmark snapshot is the reproducible demonstration when those services are unavailable.

## Gnani AI integration

The app can record a short question, send it to Gnani STT REST (`/stt/v3`, Prisma v2.5 default), show the transcript for review, and pass an edited transcript into the existing research pipeline. It can then speak only the concise result paragraph using Gnani TTS REST (`/api/v1/tts/inference`, Timbre v2.5); the full written answer and SEC evidence remain visible. The STT endpoint supports clips up to 30 seconds. See the [official STT REST guide](https://docs.gnani.ai/api/STT/speech-to-text) and [official TTS REST guide](https://docs.gnani.ai/api/TTS/tts-inference).

Set `GNANI_API_KEY_ID` in the server process environment or in the local `.streamlit/secrets.toml` file. The app reads the value server-side and sends it only in Gnani's `X-API-Key-ID` request header. Do not paste the key into chat, put it in source code, or commit `secrets.toml`; the local secrets file is ignored by Git. For hosted deployments, use the host's secrets manager. Voice requests are not sent when the key is absent. Automated tests mock the HTTP layer; **real STT/TTS account calls have not been tested yet**.

Keep API keys out of source code, chat, screenshots, logs, and commits. The repository ignores `.env` files and `.streamlit/secrets.toml`. For local Streamlit development, store secrets in a local ignored secrets file or use environment settings; for a hosted demo, use the host's secret store. Never place a key in a browser-visible component. Rotate it if it is exposed.

## Limitations and next work

- Only annual US SEC revenue growth, absolute revenue change, operating margin change, net-income/operating-income change relationship, receivables/revenue growth comparison, and cash conversion comparison have complete calculation paths.
- The planner and SEC live integration have not been jointly benchmarked against reference answers.
- Quarterly periods, segment facts, other balance-sheet calculations, and disclosure answers need complete retrieval-to-answer paths and tests.
- Narrative section extraction uses heuristics and keyword ranking; it is not yet reliable enough for material-risk answers.
- The benchmark has no fixed gold answers for its general templates. Evaluation needs declared company/filing snapshots and references for each question.
- Real Gnani STT/TTS account calls, a public demo recording, and deployment remain future work.

FinSpect is a learning-focused prototype, not financial advice. Verify results against the cited filing before relying on them.
