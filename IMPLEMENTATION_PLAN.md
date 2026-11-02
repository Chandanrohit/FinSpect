# FinSpect Implementation Plan

## Goal

Build a dependable research assistant for questions answerable from SEC filings of US-listed companies. Answers must use issuer-specific filing evidence, identify the reporting period and units, show calculations, and say when the filing does not support a reliable answer. This is broad coverage, not a promise to answer every possible question for every issuer.

The current product benchmark contains 20 reusable question archetypes in five layers. The target is to support each archetype through reusable operations that handle natural-language paraphrases and issuer data; it is not to hard-code every wording or every company. Where issuers use different valid tags, calendars, or disclosure structures, add evidence-based mappings and test them. Questions outside the benchmark or beyond available filing evidence must be identified as unsupported rather than guessed.

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

Overall benchmark report: 11 `PARTIAL`, 9 `UNSUPPORTED`, 0 `PASS`, 0 `FAIL`. Partial cases use fixture data and validated plans, not live retrieval or planner validation. Q12 now has a planner contract and an exact 10-K retrieval-to-answer path with filing metadata checks, statement-of-equity extraction, and deterministic calculation; mocked end-to-end pipeline checks cover all six NVIDIA, Microsoft, and Apple reference periods. Q14 now has exact annual fact retrieval for operating cash flow, repurchases, dividends, and cash capital expenditure; its six NVIDIA, Microsoft, and Apple FY2024/FY2025 reference calculations and mocked pipeline cases pass. Live SEC retrieval and planner evaluation remain unevaluated for both operations. Q01, Q03, Q05, and Q13 each have 8/8 passing offline cases across NVIDIA, Microsoft, Apple, and CVS Health (two annual pairs each). Q07 now has 8/8 passing cases across NVIDIA, Microsoft, Apple, and PepsiCo (two annual pairs each), adding a food and beverage issuer with distinct 52/53-week fiscal periods. Q08 and Q09 each have 6/6 passing cases across NVIDIA, Microsoft, and Apple. Q10 has 8/8 passing annual comparisons across NVIDIA, Microsoft, Apple, and CVS Health, validating repurchase cash magnitude, the current operating-cash-flow ratio, and the change from the prior-year amount; the CVS Health cases extend the matrix into health care and include a filed zero-repurchase year. Q11 has 9/9 passing annual periods across NVIDIA, Microsoft, and Apple, validating weighted-average share dilution using SEC `shares` facts. Q12 has 6/6 passing statement-of-equity calculation references across NVIDIA, Microsoft, and Apple for FY2024 and FY2025; the matrix preserves each reported row label and sign and selects the largest row by absolute amount. Q09 requires aligned point-in-time inventory balances, annual revenue, exact 10-K accession retrieval, and a linked Item 7/Item 1A inventory passage. Most matrices remain concentrated in large technology issuers; broader sector coverage remains necessary before claiming general reliability. No overall accuracy percentage is defensible yet.

Completed slices: benchmark baseline and investor-facing Streamlit home; Q01 annual revenue growth, Q03 annual operating-margin change, Q05 annual earnings-change relationship, and Q13 annual cash conversion across four issuers (including a healthcare company); Q07 annual liquid-asset contribution across four issuers, including food and beverage; Q08 annual receivables-growth comparison; Q09 annual inventory/revenue comparison with filing narrative evidence; Q10 annual share repurchase analysis across four issuers, including CVS Health; Q11 weighted-average share dilution across three issuers; and the Q12 offline statement-of-equity row-selection/calculation matrix plus six mocked retrieval-to-answer reference cases across NVIDIA, Microsoft, and Apple. Next: validate against live SEC filings, then broaden remaining operations to additional sectors, then implement Q14–Q20, quarterly support, segments, remaining narrative topics, live planner/SEC integration, Streamlit smoke-check, and local Gnani validation. These gates are offline reference coverage; live SEC, planner, and Gnani evaluation remains in Gate 5.

## Scope limits

Initial coverage targets standard US-GAAP data available in SEC filings. Custom issuer tags, IFRS reporting, foreign-currency conversion, nonstandard fiscal calendars, and narrative questions may require separate mappings or may be explicitly unsupported. FinSpect must not invent a result to meet a coverage target.
