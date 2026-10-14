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


