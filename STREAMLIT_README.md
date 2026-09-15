# COMET-Wasm Streamlit Demonstrator

This Streamlit application visualises the finalized COMET-Wasm experiments and executes the repository's real `CometScheduler` against the frozen offline characterisation database.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Streamlit Community Cloud

Main file path: `streamlit_app.py`

The cloud deployment is a scheduler/profile demonstrator. It does not launch Docker or Wasmtime inference servers. Scheduler decisions are computed from the same frozen profile database and scheduler implementation used by the research evaluation.

## Scientific interpretation

The current implementation uses offline characterisation and fixed runtime profiles. Adaptive online profile refresh is future work. The 756-decision profile-space audit selected Wasmtime 594 times, Docker 0 times, and rejected 162 infeasible cases; the application does not modify weights to manufacture backend diversity.
