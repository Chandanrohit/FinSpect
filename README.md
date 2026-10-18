# FinSpect
FinSpect is an experimental financial research assistant that combines natural-language query planning, SEC filing retrieval, evidence validation, deterministic calculations, and a Streamlit interface.

## Problem

Reading annual reports and connecting information across financial statements and disclosures takes time. FinSpect aims to help users investigate selected financial questions while preserving the source evidence and reporting periods behind its answers.

## Architecture

1. **Streamlit interface** — accepts a research question and displays the result.
2. **LLM query planner** — converts a question into a structured research plan.
3. **Plan normalizer and period resolver** — normalize known company identifiers and resolve reporting periods.
4. **SEC retrieval** — retrieves structured financial facts and filing information.
5. **Evidence and validation** — preserve provenance and check whether the retrieved inputs are suitable.
6. **Deterministic calculator** — performs supported financial calculations.
7. **Answer builder** — formats conclusions, calculations, evidence, and limitations.

Narrative disclosure retrieval is being developed for questions involving risks, litigation, and management discussion.

## Current status

The project is under active development. Unit tests cover query planning, schema validation, evidence handling, answer construction, and initial narrative retrieval.

Passing unit tests do not yet establish that every benchmark question is supported or that every answer is financially correct. End-to-end evaluation is still required.

## Run locally

Use Python 3.13 or another Python version supported by the installed dependencies.

Install the project's dependencies, then set the source path in PowerShell:

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m pytest tests/ -v
```

Launch Streamlit:

```powershell
$env:PYTHONPATH = "src"
python -m streamlit run src/finspect/app.py
```

The application may require a running local Ollama model and internet access for SEC requests. Check the configuration and model requirements before running it.

## Design principles

- Preserve source and reporting-period information.
- Keep financial arithmetic deterministic.
- Validate retrieved inputs before calculating.
- Report unsupported questions and missing evidence explicitly.
- Avoid fabricating values or citations.

## Limitations

FinSpect is a research prototype, not a financial adviser. Its coverage is limited to implemented retrieval and calculation paths. Results require verification against the original SEC filings.

## Contributing

Issues and pull requests are welcome. Please include tests for behavior changes and explain the evidence supporting any financial calculation changes.


## Project Status

**FinSpect v0.1 — Under Active Development**

FinSpect is an experimental financial analysis system designed to answer questions about company financial statements using SEC filings, structured financial facts, and deterministic calculations.

The project is being developed incrementally, with a focus on data provenance, calculation correctness, explicit validation, and reducing numerical hallucinations in LLM-assisted financial analysis.

### What Works So Far

- **SEC EDGAR integration:** Retrieve company filing information and structured financial data from SEC sources.
- **Financial fact retrieval:** Work with financial facts associated with reporting periods and accounting concepts.
- **Typed data contracts:** Use Pydantic schemas to represent financial facts, reporting periods, units, and supporting evidence.
- **Deterministic calculations:** Perform supported financial calculations using Python's `Decimal` arithmetic rather than relying on an LLM to calculate numerical results.
- **Query planning:** Use an LLM-assisted planning layer to interpret supported financial questions.
- **Streamlit interface:** Provide a user interface for submitting questions and inspecting pipeline results.
- **Initial validation and testing:** Maintain automated tests for core schemas, calculations, retrieval, and pipeline components.

### Current Functional Scope

The current end-to-end implementation focuses on **annual revenue growth** using SEC-backed financial data.

Other financial questions, including net income analysis, operating cash flow, and absolute dollar-change calculations, are not yet fully supported end-to-end.

### Work in Progress

- Strengthening financial-fact validation and evidence contracts.
- Improving reporting-period selection and query interpretation.
- Preventing unsupported questions from producing misleading answers.
- Expanding retrieval and calculation support beyond annual revenue growth.
- Evaluating the 20-question financial benchmark end-to-end.
- Improving error handling, reproducibility, and the Streamlit experience.
- Integrating Gnani AI models into the application.

### Design Principle

**LLMs interpret; validated data and deterministic code calculate.**

FinSpect aims to separate language understanding from numerical execution. Financial results should be traceable to their underlying data and reporting periods, with unsupported questions handled explicitly instead of answered through guesswork.

### Limitations

This is a work in progress, not a production-ready financial research platform. Supported functionality is limited, and results require verification against the underlying filings. Passing unit tests does not by itself establish that every financial question is supported or that all outputs are financially correct.

### Roadmap

- [x] Establish core financial schemas and calculation components.
- [x] Integrate initial SEC-backed financial-data retrieval.
- [x] Build an initial Streamlit application.
- [ ] Complete validation and evidence-contract reliability work.
- [ ] Expand supported financial metrics and query types.
- [ ] Run the benchmark end-to-end and report measured results.
- [ ] Integrate Gnani AI and evaluate the resulting user experience.
- [ ] Complete documentation, deployment preparation, and a public demo.

*Roadmap items reflect development plans and should be updated as features are completed and tested.*