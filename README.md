# FinSpect

FinSpect is a voice-enabled financial research assistant for Indian retail investors researching US companies. It lets users ask financial questions through text or voice, retrieves evidence from SEC EDGAR filings, performs deterministic financial calculations and returns answers with cited filing sources.

A locally hosted Qwen model (through Ollama) interprets the question into a structured plan. Financial calculations are handled by a separate Python calculation pipeline — the LLM does **not** perform arithmetic or produce financial figures.

> **Status: research prototype, built for the Gnani AI Great Indian AI Internship Challenge 2026.** The deterministic benchmark covers 20 question archetypes, currently classified as **20 PARTIAL, 0 PASS, 0 UNSUPPORTED, 0 FAIL**. PARTIAL means there is offline reference and pipeline coverage (126/126 fixture-backed reference cases pass), but it is not a live accuracy score. Live SEC retrieval and the live LLM planner have not been comprehensively tested together. A local planner-only sweep of all 20 templates with `qwen2.5-coder:3b` returned schema-valid plans for 15/20; five were rejected by validation, and some valid plans selected the wrong operation or benchmark ID. This was not an answer-accuracy test. See [`reports/benchmark-report.json`](reports/benchmark-report.json) and [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

---

## Architecture

FinSpect separates question interpretation (LLM) from financial calculation (deterministic Python). The LLM never produces financial figures; it only turns a natural-language question into a structured query plan that the calculation pipeline consumes.

### Text input flow

```
User question (English)
  → Local Ollama planner (qwen2.5-coder:3b)
  → Structured query plan (company, period, metrics, operation)
  → Plan normalization + validation
  → SEC EDGAR retrieval (company facts, filings, XBRL)
  → Period, unit, and identity checks
  → Deterministic Python calculation
  → Answer with formula, inputs, periods, and SEC evidence
  → Streamlit display
```

### Voice input flow

```
User audio (English, max 30 seconds)
  → Streamlit audio capture (microphone or WAV upload)
  → Local FastAPI voice service (127.0.0.1:8000)
  → Gnani Prisma v3 speech-to-text
  → Transcribed question (English)
  → User reviews / edits transcript
  → Same orchestration pipeline as text input
  → SEC EDGAR retrieval + deterministic calculation
  → Answer with evidence
```

### Optional spoken response

```
Answer text
  → prepare_spoken_summary() — concise result line, numbers spelled out
  → Local FastAPI voice service
  → Gnani Timbre v2.5 text-to-speech (English)
  → Audio playback in Streamlit
```

### Component roles

| Component | Role | Why it exists |
|---|---|---|
| **Streamlit** | Web UI | Renders the question input, voice controls, answer, and evidence |
| **FastAPI** (`voice_api.py`) | Local voice boundary | Keeps the Gnani API key server-side; never exposed to the browser |
| **Gnani Prisma v3** | Speech-to-text | Transcribes recorded/uploaded English audio |
| **Gnani Timbre v2.5** | Text-to-speech | Synthesizes a concise spoken English summary of the answer |
| **Ollama + qwen2.5-coder:3b** | Question interpretation | Turns a natural-language question into a structured, validated query plan |
| **Orchestrator** (`orchestrator.py`) | Pipeline coordinator | Connects planning → SEC retrieval → calculation → answer formatting |
| **SEC EDGAR client** | Financial data retrieval | Fetches company facts, filings, and XBRL data from SEC's public API |
| **Calculator** (`calculator.py`) | Deterministic calculation | Performs growth rates, margin changes, cash conversion, etc. in Python — no LLM arithmetic |
| **Answer builder** (`answer_builder.py`) | Answer formatting | Assembles the answer text, formula, inputs, evidence, and limitations |

---

## Resources and technologies

- **SEC EDGAR** — public US company filings (10-K, 10-Q), XBRL facts, and submissions API. No API key; requires a descriptive `SEC_USER_AGENT` with contact email.
- **Gnani AI Prisma v3** — speech-to-text for English audio transcription.
- **Gnani AI Timbre v2.5** — text-to-speech for spoken English answer summaries.
- **Ollama** — local LLM runtime hosting `qwen2.5-coder:3b` for question interpretation.
- **FastAPI** — local voice service boundary (port 8000).
- **Streamlit** — application interface (port 8501).
- **Python 3.11+** with Pydantic, requests, python-multipart, beautifulsoup4, uvicorn.
- **Pytest** — 328 backend tests covering schema validation, calculator, planner (mocked), SEC retrieval (mocked), and voice API.

---

## Run locally (Windows PowerShell)

### 1. Install the project

Use Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### 2. Configure SEC access and Ollama

SEC's public endpoints do not use an API key. SEC asks clients to identify themselves with a descriptive User-Agent and contact email.

```powershell
$env:SEC_USER_AGENT = "FinSpect Student Developer your-email@example.com"
$env:FINSPECT_OLLAMA_MODEL = "qwen2.5-coder:3b"
$env:FINSPECT_OLLAMA_TIMEOUT = "300"
$env:FINSPECT_OLLAMA_NUM_CTX = "4096"
$env:FINSPECT_OLLAMA_NUM_PREDICT = "512"
```

Install the default model once:

```powershell
ollama pull qwen2.5-coder:3b
```

> **Why `ollama pull`?** Ollama stores model weights on disk. The `ollama serve` command starts the daemon, but the model weights must be downloaded once before the HTTP API (`/api/generate`) can serve inference. `ollama pull qwen2.5-coder:3b` downloads the ~1.9 GB model weights. `ollama run qwen2.5-coder:3b` would also auto-pull on first use, but FinSpect calls the HTTP API directly (not the CLI), so the model must already be available locally. You cannot skip the pull — the weights are not bundled with the Ollama binary.

Make sure Ollama is running as a service. If it is not already running, open a separate PowerShell window and run `ollama serve`. The default endpoint is `http://localhost:11434`.

### 3. (Optional) Configure Gnani voice

Text questions need no Gnani credentials. For voice, paste your single shared key into the local, Git-ignored file `.streamlit/secrets.toml`:

```toml
GNANI_API_KEY_ID = "[Paste API Key]"
```

This file is ignored by Git. The FastAPI voice service reads the key server-side and sends it in Gnani's `X-API-Key-ID` header for both STT and TTS. The dashboard never displays or accepts keys.

### 4. Start the local voice backend (Terminal 2)

```powershell
cd D:\Finspect\v0.1
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
$env:SEC_USER_AGENT = "FinSpect Student Developer your-email@example.com"
python -m uvicorn finspect.voice_api:app --host 127.0.0.1 --port 8000
```

Confirm it is ready at `http://127.0.0.1:8000/health`; `gnani_configured` should be `true` after adding the key.

### 5. Start Streamlit (Terminal 3)

```powershell
cd D:\Finspect\v0.1
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
$env:SEC_USER_AGENT = "FinSpect Student Developer your-email@example.com"
$env:FINSPECT_VOICE_API_URL = "http://127.0.0.1:8000"
python -m streamlit run src\finspect\app.py
```

Open the local URL Streamlit prints (usually `http://localhost:8501`).

### Quick verification

```powershell
# Terminal 1: Ollama running?
Invoke-RestMethod http://127.0.0.1:11434/api/tags

# Terminal 2: Voice API healthy?
Invoke-RestMethod http://127.0.0.1:8000/health
```

---

## Current coverage

The benchmark covers 20 question archetypes (Q01–Q20) across annual and quarterly financial statements:

| ID | Question type | Issuers covered |
|---|---|---|
| Q01 | Annual revenue growth | NVDA, MSFT, AAPL, CVS |
| Q02 | Segment revenue contribution | NVDA, MSFT, AAPL |
| Q03 | Operating margin change | NVDA, MSFT, AAPL, CVS |
| Q04 | Operating expense contribution | NVDA, MSFT, AAPL |
| Q05 | Net income / operating income change | NVDA, MSFT, AAPL, CVS |
| Q06 | Equity rollforward | NVDA, MSFT, AAPL |
| Q07 | Inventory revenue growth comparison | NVDA, MSFT, AAPL, PEP |
| Q08 | Receivables growth comparison | NVDA, MSFT, AAPL |
| Q09 | Dilution ratio | NVDA, MSFT, AAPL |
| Q10 | Share repurchase comparison | NVDA, MSFT, AAPL, CVS |
| Q11 | Earnings relationship | NVDA, MSFT, AAPL |
| Q12 | Equity component contribution | NVDA, MSFT, AAPL |
| Q13 | Cash conversion comparison | NVDA, MSFT, AAPL, CVS |
| Q14 | Cash allocation | NVDA, MSFT, AAPL |
| Q15 | Commitment liquidity | NVDA, MSFT, AAPL |
| Q16 | Regulatory risk analysis | NVDA, MSFT, AAPL |
| Q17 | Market risk sensitivity | NVDA, MSFT, AAPL |
| Q18 | Geographic revenue exposure | NVDA, MSFT, AAPL |
| Q19 | Legal proceedings | NVDA, MSFT, AAPL |
| Q20 | Material disclosure synthesis | NVDA, MSFT, AAPL |

**Fixture-backed reference cases: 126/126 pass.** These verify the calculator and pipeline logic against known SEC values. They do **not** verify live SEC retrieval or live LLM planner output.

**Quarterly Q1–Q3 revenue growth** has source-linked NVIDIA, Microsoft, and Apple references (3/3 per quarter). Q4 and quarter-to-quarter comparisons are not implemented.

---

## Current limitations

FinSpect is an early-stage research prototype. Known limitations:

1. **English only.** The application supports English input and output only. Multilingual input (speaking or typing in Hindi, Tamil, etc.) and multilingual output are not supported. Gnani Prisma STT and Timbre TTS are configured for English (`en-IN`). The LLM planner works best with English questions.

2. **One question at a time.** The application processes one question per submission. Multi-part questions (e.g., "Compare revenue and operating margin and cash conversion") may confuse the planner or produce an unsupported-answer response. Ask each question separately.

3. **LLM for interpretation only.** The local Qwen model interprets the question into a structured plan. It does **not** perform financial calculations, produce figures, or retrieve data. All arithmetic is handled by the deterministic Python calculator.
Imp: Local LLM planner limitation. The default model qwen2.5-coder:3b (3B parameters, coder-trained) reliably interprets only simple single-metric questions — annual revenue growth (Q01) and operating margin change (Q03). Multi-metric questions (receivables vs revenue, net income vs operating income), cross-statement reasoning (earnings bridge) and questions where the operation must be inferred from context (cash conversion, equity rollforward) frequently fail because the planner produces an invalid plan or selects the wrong operation. A local planner-only sweep returned schema-valid plans for 15/20 templates; 5 were rejected, and some valid plans selected the wrong operation or benchmark ID. This is a model capacity limitation, not a calculator limitation — the deterministic calculator passes 126/126 fixture-backed reference cases. To improve planner reliability, consider a larger or instruction-tuned model (e.g., qwen2.5:7b, llama3.2:4b) by setting FINSPECT_OLLAMA_MODEL or using other model such as (ProsusAI/FinBERT, FinancialBERT, FLANG) or you can use api's better for better intrepretation and output.


4. **Planner accuracy is not verified live.** A local planner-only sweep of all 20 templates with `qwen2.5-coder:3b` returned schema-valid plans for 15/20. Five were rejected by validation. Some valid plans selected the wrong operation or benchmark ID. Live planner accuracy against the benchmark has not been measured.

5. **Live SEC + planner not tested together.** The benchmark uses fixture-backed reference cases (offline). End-to-end live accuracy (real SEC EDGAR + real planner output) has not been measured.

6. **Limited issuer coverage.** Annual reference matrices include NVIDIA, Microsoft, Apple, CVS Health, PepsiCo, and Amazon across operations. Coverage is uneven. Custom issuer tags, IFRS data, and FX conversion are not supported.

7. **Quarterly limits.** Q1–Q3 year-over-year revenue growth is supported. Q4, direct YTD answers, and quarter-to-quarter comparisons are not implemented.

8. **Latency.** SEC EDGAR retrieval and Ollama planner inference introduce latency (typically 10–60 seconds per question depending on network and model load).

9. **Voice networking.** Microphone capture requires localhost or HTTPS. Plain HTTP LAN URLs will load the page but the browser blocks recording. Audio integration and networking require further refinement.

10. **No accuracy guarantee.** The benchmark does not establish that every question works correctly. Verify important results against the cited SEC filing.

---

## Testing

```powershell
# Run the full backend test suite (mocked planner + mocked SEC)
.\.venv\Scripts\python.exe -m pytest -q

# Regenerate the deterministic benchmark report
.\.venv\Scripts\python.exe -m finspect.benchmark_eval --output reports/benchmark-report.json
```

Expected: **328 passing tests** and a report with **20 PARTIAL, 0 FAIL**.

For a live smoke check: (1) verify Ollama is reachable and has the model, (2) verify the voice API `/health` endpoint, (3) verify SEC_USER_AGENT is set in the Streamlit terminal, (4) ask a bounded supported question and check the result's periods, values, units, and SEC filing links.

---

## Gnani API notes

The optional voice flow uses Gnani Prisma v3 for speech-to-text (`/stt/v3`) and Timbre v2.5 for text-to-speech (`/api/v1/tts/inference`). The app shows the transcript for review before research and speaks only a concise result summary. Written answers and SEC evidence remain visible. See the [Gnani STT guide](https://docs.gnani.ai/api/STT/speech-to-text) and [Gnani TTS guide](https://docs.gnani.ai/api/TTS/tts-inference).

There is no hosted LLM API key in the text workflow: Ollama runs locally. SEC access uses the descriptive `SEC_USER_AGENT`, not a secret. Keep Gnani credentials server-side and rotate them if exposed.

---

## Project structure

```
src/finspect/
  app.py              # Streamlit UI (text + voice input, answer display)
  voice_api.py        # FastAPI voice boundary (Gnani STT + TTS)
  gnani_voice.py      # Gnani API client (server-side key handling)
  orchestrator.py     # Pipeline coordinator: plan → retrieve → calculate → answer
  llm_planner.py      # Ollama-backed query planner
  query_planner.py    # Query plan Pydantic schema
  plan_normalizer.py  # Deterministic plan normalization
  period_resolver.py  # Fiscal period resolution
  calculator.py       # Deterministic financial calculations
  answer_builder.py   # Answer + evidence formatting
  evidence.py         # Evidence validation
  edgar/              # SEC EDGAR client, facts, filings, parser, extractors
  schema.py           # Benchmark schema and loading
  benchmark_eval.py   # Deterministic benchmark evaluator
tests/                # 328 backend tests (mocked planner + mocked SEC)
data/fixtures/        # Offline SEC reference matrices
data/benchmark.json   # 20 benchmark question definitions
.streamlit/config.toml  # Streamlit theme + server config
```

FinSpect is a prototype, not financial advice. Verify important results against the cited filing.
