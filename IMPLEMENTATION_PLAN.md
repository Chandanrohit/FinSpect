# FinSpect Implementation Plan

## Goal

Build a dependable research assistant for questions answerable from SEC filings of US-listed companies. Answers must use issuer-specific filing evidence, identify the reporting period and units, show calculations, and say when the filing does not support a reliable answer. This is broad coverage, not a promise to answer every possible question for every issuer.

The current product benchmark contains 20 reusable question archetypes in five layers. The target is to support each archetype through reusable operations that handle natural-language paraphrases and issuer data; it is not to hard-code every wording or every company. Where issuers use different valid tags, calendars, or disclosure structures, add evidence-based mappings and test them. Questions outside the benchmark or beyond available filing evidence must be identified as unsupported rather than guessed.

## Design principles

- **LLM for interpretation only.** The local Qwen model (qwen2.5-coder:3b via Ollama) interprets the question into a structured query plan. It does not perform calculations, produce financial figures, or retrieve data. All arithmetic is handled by the deterministic Python calculator.
- **English only.** The application supports English input and output only. Multilingual input and output are not supported. Gnani Prisma STT and Timbre TTS are configured for English (en-IN).
- **One question at a time.** The application processes one question per submission. Multi-part questions may confuse the planner or return an unsupported-answer response.
- **Calculation is separate from interpretation.** The LLM produces a plan; the calculator consumes it. This separation ensures financial results are deterministic and verifiable, not LLM-generated.

## Benchmark rules

- Use fixed, versioned cases with a named issuer, filing accession, question, expected inputs, expected result or required evidence, and source links. Generic question templates without gold inputs do not count as evaluated coverage.
- A case passes only when issuer, filing, period, concept, unit, calculation or cited disclosure, and answer agree with its reference. Unsupported answers are correct only for cases explicitly marked unsupported in the reference.
- Never average away a wrong-company, wrong-period, wrong-currency, fabricated-value, or fabricated-citation error. Any such error blocks the gate.
- Keep offline fixture results separate from live SEC/Ollama integration results. Report coverage counts and critical-error counts; do not call fixture-only results live accuracy.
- A benchmark gate is reached when its minimum case coverage is met, every evaluated case passes, and there are zero critical errors. Commit the complete slice and its fixtures/report at that point.

## Ordered work and commit gates

### Gate 0 — benchmark baseline

Keep all 20 question IDs classified and make unsupported work visible, while preserving exact reference cases for the operations already implemented. Do not turn generic templates into fake gold cases: add named issuers, filing accessions, expected inputs, and source-backed results as each operation is implemented. Establish a deterministic report that distinguishes `PASS`, `PARTIAL`, `UNSUPPORTED`, and `FAIL` and never reports accuracy for cases without references.

**Exit:** all 20 cases are accounted for; each implemented case reproduces its expected inputs, period, currency, calculation, and evidence; unsupported cases state why; zero critical errors. Commit the baseline and its report.

### Gate 1 — generic annual financial-statement retrieval

Extend common annual financial-statement questions across multiple issuers, beginning with revenue growth and then operating income/margin, net income, cash flow, receivables, inventory, and balance-sheet facts. Prioritize standard SEC US-GAAP tags and add aliases only where issuer evidence justifies them.

**Exit:** at least 3 issuers and 2 fiscal-year pairs per implemented operation; 100% of gated reference cases pass; zero issuer, period, unit, or evidence errors; unsupported/missing facts fail closed. Commit each completed operation group when it meets this gate.

### Gate 2 — quarterly and comparative-period support

Resolve quarterly, year-to-date, and comparable-period facts without mixing durations, fiscal calendars, or amended filings.

**Exit:** reference cases cover at least 3 issuers with differing fiscal year ends; all gated period and calculation checks pass with zero critical errors. Commit.

### Gate 3 — segments and other structured disclosures

Retrieve segment, geographic, and other disclosed structured data. Preserve issuer-specific labels and avoid treating unlike segment classifications as interchangeable.

**Exit:** each supported question type passes reference cases from at least 3 issuers, including an issuer with a custom taxonomy where relevant; unsupported disclosures are explicit. Commit each question type.

### Gate 4 — filing narrative answers

Build filing-section-aware retrieval for risks, commitments, legal proceedings, market risk, and material changes. Answers must cite exact filing sections and distinguish disclosed facts from interpretation.

**Exit:** per-topic reference cases cover multiple issuers; every material claim has supporting filing evidence; no unsupported claim is presented as fact. Commit each topic group.

### Gate 5 — live integration and release readiness

Evaluate SEC retrieval and the query planner together, then exercise the Streamlit workflow and Gnani STT/TTS with secrets configured locally by the owner. Add operational limits, observability without secrets, and deployment guidance.

**Exit:** live cases match the offline reference outcomes; zero critical errors; secret-handling review finds no key in browser code, logs, repository, or chat. Commit and prepare the local/repository release.

### Investor-facing Streamlit experience

Keep the first screen focused on asking a company question. Use familiar investing app patterns such as company-first search, concise results, and visible source documents. Show only verified example prompts, keep evidence and methodology available without overwhelming the answer, and make voice an optional secondary workflow.

**Exit:** first-use workflow is understandable without developer terminology; unsupported benchmark templates are not offered as ready-to-run prompts; verified examples, evidence, errors, and voice flow render correctly in a local smoke check. Include this work in a benchmark-qualified commit.

## Current state

### Test coverage

- **328 backend tests pass** (mocked planner + mocked SEC retrieval).
- **126/126 fixture-backed reference cases pass** across Q01–Q20 (calculator and pipeline logic verified against known SEC values).
- **Benchmark: 20 PARTIAL, 0 PASS, 0 UNSUPPORTED, 0 FAIL.** PARTIAL means offline reference coverage exists but live accuracy has not been measured.

### Planner reliability (qwen2.5-coder:3b)

A local planner-only sweep of all 20 templates returned:
- **15/20 schema-valid plans** (5 rejected by Pydantic validation).
- Some valid plans selected the **wrong operation or benchmark ID**.
- This was not an answer-accuracy test; the SEC User-Agent was not configured for that run.

**Reliably working question types (live planner + live SEC):**
- **Q01 — Annual revenue growth**: "Calculate NVIDIA's revenue growth from FY2024 to FY2025." ✓
- **Q03 — Operating margin change**: "How did NVIDIA's operating margin change from FY2024 to FY2025?" ✓

**Question types with calculator coverage but unreliable live planner:**
- Q05 (earnings bridge), Q06 (equity rollforward), Q07 (liquid assets), Q08 (receivables vs revenue), Q09 (inventory vs revenue), Q10 (share repurchase), Q11 (dilution), Q12 (equity component), Q13 (cash conversion), Q14 (cash allocation), Q15 (commitment liquidity), Q16 (regulatory risk), Q17 (market risk), Q18 (geographic revenue), Q19 (legal proceedings), Q20 (material disclosure).

These have passing fixture-backed reference cases (calculator works) but the live qwen2.5-coder:3b planner frequently fails to produce the correct plan for them. This is a **model capacity limitation**, not a calculator limitation.

### Voice integration

- Gnani Prisma v3 STT: configured for English (en-IN). Voice service runs on FastAPI at `127.0.0.1:8000`.
- Gnani Timbre v2.5 TTS: configured for English (en-IN). Synthesizes a concise spoken summary of the answer.
- Voice backend health check: `GET /health` returns `{"status":"ok","gnani_configured":bool}`.
- Real Gnani STT/TTS account calls have not yet been verified end-to-end.

### Quarterly coverage

Q1, Q2, and Q3 year-over-year revenue growth has source-linked NVIDIA, Microsoft, and Apple references (3/3 per quarter). A separate YTD-derived Q2/Q3 matrix passes 6/6 references across all three issuers. Q4, direct YTD answers, and quarter-to-quarter comparisons are not implemented.

## Known limitations

1. **English only.** No multilingual input or output. Gnani STT/TTS configured for en-IN.
2. **One question at a time.** Multi-part questions are not supported.
3. **LLM for interpretation only.** The Qwen model does not perform calculations.
4. **Planner accuracy not verified live.** 15/20 schema-valid plans; some valid plans select wrong operation. Only Q01 and Q03 are confirmed reliable with the live planner.
5. **Live SEC + planner not tested together** across the full benchmark.
6. **Limited issuer coverage.** NVDA, MSFT, AAPL, CVS, PEP in some matrices.
7. **Q4 and quarter-to-quarter comparisons** not implemented.
8. **Latency.** 10–60 seconds per question (Ollama inference + SEC retrieval).
9. **Voice requires localhost or HTTPS** for microphone capture.
10. **No accuracy guarantee.** Verify important results against cited SEC filings.

## Next priorities

1. **Improve planner reliability.** Test with larger or instruction-tuned models (e.g., `qwen2.5:7b`, `llama3.2:3b`) by setting `FINSPECT_OLLAMA_MODEL`. Evaluate which question types become reliable.
2. **Live end-to-end testing.** Run the full benchmark with live SEC + live planner to measure actual accuracy. Currently 0/20 questions have live accuracy verified.
3. **Extend quarterly references** to additional sectors and Q4/direct-YTD questions.
4. **Complete Gnani STT/TTS account verification** with real API calls.
5. **Expand issuer coverage** beyond large technology companies.
6. **Do not expand multilingual support** until the English pipeline has measured live accuracy. English-only is the current scope.

## Scope limits

Initial coverage targets standard US-GAAP data available in SEC filings. Custom issuer tags, IFRS reporting, foreign-currency conversion, nonstandard fiscal calendars, multilingual input/output, and narrative questions may require separate mappings or may be explicitly unsupported. FinSpect must not invent a result to meet a coverage target.
