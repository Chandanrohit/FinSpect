# FinSpect

FinSpect is an experimental financial research assistant for information in US SEC filings. A local Ollama model turns a question into a structured plan; FinSpect retrieves SEC evidence, checks company and period metadata, and uses deterministic Python calculations for supported numeric questions. Answers include periods and source evidence, and unsupported or ambiguous requests should fail closed.

> **Status: research prototype.** The deterministic report covers 20 question archetypes, currently classified as **20 PARTIAL, 0 PASS, 0 UNSUPPORTED, 0 FAIL**. PARTIAL means there is offline reference and pipeline coverage, but it is not a live accuracy score. A separate Q1 year-over-year revenue gate passes **3/3** reference cases (NVIDIA, Microsoft, Apple). SEC retrieval and planner interpretation have not been evaluated together across the benchmark. See [`reports/benchmark-report.json`](reports/benchmark-report.json) and [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## How it works

```mermaid
flowchart LR
    Q[Question] --> P[Local Ollama planner]
    P --> N[Validated query plan]
    N --> R[SEC company and filing retrieval]
    R --> V[Period, unit, identity and evidence checks]
    V --> C[Deterministic calculation or filing extraction]
    C --> A[Answer with periods and SEC sources]
```

The Streamlit interface presents the plan, answer, and evidence from the same research pipeline. It does not calculate financial values in the browser.

## Run locally (Windows PowerShell)

### 1. Install the project

Use Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 2. Configure SEC access and Ollama

SEC's public endpoints do not use an API key. SEC asks clients to identify themselves with a descriptive User-Agent and contact email. Set your own contact value in the terminal where Streamlit will run:

```powershell
$env:SEC_USER_AGENT = "FinSpect/0.1 contact your-email@example.com"
$env:FINSPECT_OLLAMA_MODEL = "qwen2.5-coder:3b"
$env:FINSPECT_OLLAMA_TIMEOUT = "300"
$env:FINSPECT_OLLAMA_NUM_CTX = "4096"
$env:FINSPECT_OLLAMA_NUM_PREDICT = "512"
```

Install the default model once if needed:

```powershell
ollama pull qwen2.5-coder:3b
```

Make sure Ollama is running. If it is not already running as a service, open another PowerShell window and run `ollama serve`. The default endpoint is `http://localhost:11434`; set `FINSPECT_OLLAMA_URL` if yours is different.

### 3. (Optional) Configure Gnani voice

Text questions need no Gnani credentials. For voice, paste your single shared key into the local, Git-ignored file `D:\Finspect\v0.1\.streamlit\secrets.toml` (create the `.streamlit` folder if needed):

```toml
GNANI_API_KEY_ID = "your Gnani API key ID"
```

This file is ignored by Git. The app reads the key server-side and sends it in Gnani's `X-API-Key-ID` header for both services; it never displays or accepts keys on the dashboard. Restart Streamlit after adding the key. Do not put credentials in source code, screenshots, chat, or commits. Real STT/TTS account calls have not yet been verified.

### 4. Start Streamlit

In the PowerShell window with the SEC settings, run:

```powershell
python -m streamlit run src/finspect/app.py
```

Open the local URL Streamlit prints, usually `http://localhost:8501`. Try a bounded supported question such as:

> For NVIDIA, what was the year-over-year revenue growth in fiscal Q1 2025 compared with fiscal Q1 2024?

The quarterly reference gate covers Q1 revenue only. For annual examples, try Microsoft's FY2024-to-FY2025 revenue growth or an NVIDIA annual operation. Check the result's periods, values, units, and SEC filing links before relying on it.

### If the local model is slow or runs out of context

FinSpect sends a compact planning prompt and schema, not the full chat history. Ollama requests use a 4,096-token context by default and allow 300 seconds for the planner response. A larger context uses more memory; raise `FINSPECT_OLLAMA_NUM_CTX` only if Ollama reports a context-length error and your machine has enough memory. If the client times out while the model is still responding, raise `FINSPECT_OLLAMA_TIMEOUT` (for example, to `600`); this waits longer but does not make inference faster. Keep `FINSPECT_OLLAMA_NUM_PREDICT` near `512` for the structured plan output.

## Check whether it is working

Run the automated suite and regenerate the deterministic benchmark report from the repository root:

```powershell
python -m pytest -q
python -m finspect.benchmark_eval --output reports/benchmark-report.json
```

The expected current baseline is **301 passing tests** and a report with **20 PARTIAL, 0 FAIL**. The report includes per-operation reference matrices; check their case counts and failed checks, not just the aggregate. For the Q1 revenue slice, expect 3 cases and 3 passes for NVDA, MSFT, and AAPL. These checks use fixed references and mocks, so they do not prove that today's SEC response or an LLM plan will be correct.

For a local live smoke check, verify that (1) Ollama is reachable and has the selected model, (2) the app starts without a configuration error, (3) a question returns a plan and answer, and (4) each cited filing, period, unit, and calculation agrees with the SEC filing. A live SEC request needs internet access and a valid `SEC_USER_AGENT`. Stop if the planner picks the wrong issuer, fiscal period, metric, or evidence; record the question and result as a benchmark case before treating the issue as fixed.

## Current coverage and limits

- The annual pipeline supports the implemented Q01–Q20 archetypes across financial statements, segments, cash allocation, equity, commitments, risks, legal proceedings, market-risk disclosures, and selected narrative questions. Support and reference depth vary by operation; the benchmark report and [`data/benchmark`](data/benchmark) are the source of truth for individual cases.
- Q1 year-over-year revenue growth supports standalone Q1 10-Q periods and has NVIDIA, Microsoft, and Apple references across different fiscal calendars. Q2/Q3 standalone derivation and Q4 or quarter-to-quarter comparisons are not implemented.
- Annual reference matrices include NVIDIA, Microsoft, Apple, CVS Health, PepsiCo, and Amazon across operations. Coverage is uneven and remains limited; it does not establish support for every US-listed company or every question.
- Live SEC retrieval and Ollama planning have not been comprehensively tested together against the reference benchmark. The checked-in report is deterministic and does not make an overall accuracy claim.
- A local planner-only sweep of all 20 templates with `qwen2.5-coder:3b` returned schema-valid plans for 15/20; five were rejected by validation, and some valid plans selected the wrong operation or benchmark ID. This was not an answer-accuracy test. The SEC User-Agent was not configured for that run, so no live SEC answer sweep was performed.
- Q20 topic matching is bounded and is not an exhaustive risk analysis or validated materiality ranking. Narrative extraction has heuristic limits.
- Custom issuer tags, IFRS data, FX conversion, and disclosures that are missing, ambiguous, or incompatible with the requested periods may be unsupported. FinSpect is a prototype, not financial advice; verify important results against the cited filing.

## Next implementation priorities

1. Extend the quarterly resolver to Q2/Q3 using period-safe standalone-quarter derivation from SEC year-to-date facts; add references spanning fiscal calendars and amended filings.
2. Add source-backed cases for more sectors and less-covered operations, and test both live SEC retrieval and planner interpretation against expected references.
3. Complete a Streamlit research-flow smoke check and Gnani STT/TTS account check with secrets configured locally; document any deployment-specific setup.
4. Expand only after a question type has clear reference cases. Keep unsupported behavior explicit instead of guessing.

See [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) for the ordered benchmark gates and exit criteria.

## Gnani API notes

The optional voice flow uses Gnani Prisma v2.5 for speech-to-text (`/stt/v3`) and Timbre v2.5 for text-to-speech (`/api/v1/tts/inference`). The app shows the transcript for review before research and speaks only a concise result summary; written answers and SEC evidence remain visible. See the [Gnani STT guide](https://docs.gnani.ai/api/STT/speech-to-text) and [Gnani TTS guide](https://docs.gnani.ai/api/TTS/tts-inference). Automated tests mock provider requests; a real account call remains to be done.

There is no hosted LLM API key in the current text workflow: Ollama runs locally. SEC access uses the descriptive `SEC_USER_AGENT`, not a secret. Keep Gnani credentials server-side, and rotate them if they are exposed.
