# FinSpect Implementation Plan

## Goal

Build a dependable research assistant for questions answerable from SEC filings of US-listed companies. Answers must use issuer-specific filing evidence, identify the reporting period and units, show calculations, and say when the filing does not support a reliable answer. This is broad coverage, not a promise to answer every possible question for every issuer.

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

## Current state and next slice

Overall benchmark report: 5 `PARTIAL`, 15 `UNSUPPORTED`, 0 `PASS`, 0 `FAIL`. The five partial cases use fixture data and validated plans, not live retrieval or planner validation. The Q01 reference matrix separately has 6/6 passing offline cases across NVIDIA, Microsoft, and Apple (two annual pairs each), also with no live retrieval. No overall accuracy percentage is defensible yet.

Completed slices: benchmark baseline and investor-facing Streamlit home; Q01 annual revenue growth reference matrix across three issuers. Next: extend Gate 1 to one additional annual financial statement operation and meet its own multi-issuer reference gate before committing it.

## Scope limits

Initial coverage targets standard US-GAAP data available in SEC filings. Custom issuer tags, IFRS reporting, foreign-currency conversion, nonstandard fiscal calendars, and narrative questions may require separate mappings or may be explicitly unsupported. FinSpect must not invent a result to meet a coverage target.
