# COMET-Wasm Research Dashboard

An interactive Streamlit dashboard for the experimental results in
[sallar-khan-dev/COMET-Wasm](https://github.com/sallar-khan-dev/COMET-Wasm).

## What is visualized

- Model correctness and Python/Wasmtime/Docker semantic equivalence
- Wasmtime vs Docker throughput across concurrency
- P95 and P99 tail latency
- Throughput speedup / relative performance
- Cold-start and cold-to-result latency
- Multi-tenant PSS memory density at 20, 100 and 200 tenants
- Per-tenant memory-growth rate
- Full CSV/JSON result explorer
- Research-oriented cross-model findings

The app automatically discovers finalized performance comparison CSV files and
exposes every committed CSV/JSON file under `results/`.

## Local execution

```bash
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Public deployment (recommended)

Use Streamlit Community Cloud:

1. Push `streamlit_app.py`, `.streamlit/config.toml`, and the updated `requirements.txt`
   to the repository.
2. Sign in to https://share.streamlit.io with GitHub.
3. Create an app from `sallar-khan-dev/COMET-Wasm`.
4. Branch: `main`
5. Main file path: `streamlit_app.py`
6. Deploy.

Once deployed, changes pushed to GitHub are reflected automatically in the public app.
