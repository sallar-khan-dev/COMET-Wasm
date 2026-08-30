from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CORRECTNESS_DIR = RESULTS / "correctness"
PROCESSED_DIR = RESULTS / "processed"
PERF_DIR = PROCESSED_DIR / "performance"
COLD_DIR = PROCESSED_DIR / "cold_start"
DENSITY_DIR = PROCESSED_DIR / "density"

REPO_URL = "https://github.com/sallar-khan-dev/COMET-Wasm"

st.set_page_config(
    page_title="COMET-Wasm | Research Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Visual system ----------
WASM = "#6C63FF"
DOCKER = "#2496ED"
PYTHON = "#F2C94C"
GOOD = "#22C55E"
WARN = "#F59E0B"
TEXT = "#E5E7EB"
MUTED = "#94A3B8"
CARD = "#101827"

st.markdown(
    f"""
    <style>
    :root {{
      --wasm:{WASM}; --docker:{DOCKER}; --good:{GOOD};
      --muted:{MUTED}; --card:{CARD};
    }}
    .stApp {{
      background:
        radial-gradient(circle at 12% 4%, rgba(108,99,255,.13), transparent 28%),
        radial-gradient(circle at 85% 10%, rgba(36,150,237,.10), transparent 30%),
        #07101d;
      color: {TEXT};
    }}
    [data-testid="stSidebar"] {{
      background: linear-gradient(180deg,#091322 0%,#080f1a 100%);
      border-right:1px solid rgba(148,163,184,.15);
    }}
    .block-container {{padding-top:1.2rem; padding-bottom:2.4rem; max-width:1500px;}}
    .hero {{
      border:1px solid rgba(148,163,184,.18);
      background:linear-gradient(135deg,rgba(108,99,255,.16),rgba(36,150,237,.07));
      border-radius:20px; padding:1.35rem 1.55rem; margin-bottom:1rem;
      box-shadow:0 16px 50px rgba(0,0,0,.20);
    }}
    .hero h1 {{margin:0 0 .25rem 0; font-size:2.2rem;}}
    .hero p {{margin:0;color:{MUTED};font-size:1.02rem}}
    .badge {{
      display:inline-block;padding:.22rem .55rem;border-radius:999px;
      background:rgba(108,99,255,.16);border:1px solid rgba(108,99,255,.35);
      margin-right:.35rem;font-size:.78rem;color:#DAD7FF;
    }}
    .finding {{
      border-left:4px solid {WASM}; background:rgba(15,23,42,.75);
      border-radius:10px;padding:.8rem 1rem;margin:.45rem 0;
    }}
    .metric-note {{color:{MUTED};font-size:.82rem;margin-top:-.4rem}}
    div[data-testid="stMetric"] {{
      background:rgba(15,23,42,.72);
      border:1px solid rgba(148,163,184,.16);
      padding:.85rem;border-radius:14px;
    }}
    .stDataFrame {{border:1px solid rgba(148,163,184,.12);border-radius:12px}}
    a {{color:#8FB8FF!important}}
    </style>
    """,
    unsafe_allow_html=True,
)

PLOTLY_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=TEXT),
    margin=dict(l=25, r=20, t=50, b=25),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    hoverlabel=dict(bgcolor="#0F172A"),
)


# ---------- Data helpers ----------
def pretty_model(name: str) -> str:
    aliases = {
        "mlp": "MLP",
        "svm": "SVM",
        "kmeans": "K-Means",
        "naive_bayes": "Naive Bayes",
        "logistic_regression": "Logistic Regression",
        "decision_tree": "Decision Tree",
        "random_forest": "Random Forest",
    }
    k = name.lower().strip().replace("-", "_").replace(" ", "_")
    return aliases.get(k, name.replace("_", " ").replace("-", " ").title())


@st.cache_data(show_spinner=False)
def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def first_existing(df: pd.DataFrame, names: Iterable[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def numeric(df: pd.DataFrame, col: str | None) -> pd.Series:
    if not col or col not in df:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def fmt_num(v: Any, digits: int = 2, suffix: str = "") -> str:
    try:
        if pd.isna(v):
            return "—"
        return f"{float(v):,.{digits}f}{suffix}"
    except Exception:
        return "—"


def find_files(folder: Path, pattern: str) -> list[Path]:
    return sorted(folder.glob(pattern)) if folder.exists() else []


def all_result_files() -> list[Path]:
    if not RESULTS.exists():
        return []
    return sorted(
        p for p in RESULTS.rglob("*")
        if p.is_file() and p.suffix.lower() in {".csv", ".json"}
    )


@st.cache_data(show_spinner=False)
def correctness_table() -> pd.DataFrame:
    rows = []
    if not CORRECTNESS_DIR.exists():
        return pd.DataFrame()

    for p in sorted(CORRECTNESS_DIR.glob("*.json")):
        try:
            d = load_json(str(p))
        except Exception:
            continue
        if not isinstance(d, dict) or "model" not in d or "accuracy" not in d:
            continue

        acc = d.get("accuracy", {}) or {}
        eq = d.get("equivalence", {}) or {}
        rows.append({
            "Model": pretty_model(str(d.get("model", p.stem))),
            "Dataset": d.get("dataset", "—"),
            "Samples": d.get("samples"),
            "Python": acc.get("python_reference"),
            "Wasmtime": acc.get("wasmtime"),
            "Docker": acc.get("docker"),
            "Equivalent": eq.get("all_backends_equivalent"),
            "Python↔Wasmtime failures": eq.get("python_vs_wasmtime_failures"),
            "Python↔Docker failures": eq.get("python_vs_docker_failures"),
            "Wasmtime↔Docker failures": eq.get("wasmtime_vs_docker_failures"),
            "Source": p.name,
        })
    return pd.DataFrame(rows)


def performance_files() -> dict[str, Path]:
    files = {}
    if not PERF_DIR.exists():
        return files
    for p in sorted(PERF_DIR.glob("*_performance_final_comparison.csv")):
        name = p.name.replace("_performance_final_comparison.csv", "")
        files[pretty_model(name)] = p
    return files


def perf_schema(df: pd.DataFrame) -> dict[str, str | None]:
    return {
        "conc": first_existing(df, ["concurrency"]),
        "wrps": first_existing(df, ["wasmtime_rps", "throughput_rps_wasmtime"]),
        "drps": first_existing(df, ["docker_rps", "throughput_rps_docker"]),
        "wp95": first_existing(df, ["wasmtime_p95_ms", "p95_latency_ms_wasmtime"]),
        "dp95": first_existing(df, ["docker_p95_ms", "p95_latency_ms_docker"]),
        "wp99": first_existing(df, ["wasmtime_p99_ms", "p99_latency_ms_wasmtime"]),
        "dp99": first_existing(df, ["docker_p99_ms", "p99_latency_ms_docker"]),
        "ratio": first_existing(df, ["rps_ratio_wasmtime_over_docker", "throughput_ratio_wasmtime_to_docker"]),
        "imp": first_existing(df, ["throughput_improvement_pct"]),
        "p95red": first_existing(df, ["p95_reduction_pct"]),
        "p99red": first_existing(df, ["p99_reduction_pct"]),
        "wstatus": first_existing(df, ["wasmtime_ci_status", "status_wasmtime"]),
        "dstatus": first_existing(df, ["docker_ci_status", "status_docker"]),
    }


def cold_table() -> pd.DataFrame:
    p = COLD_DIR / "cold_start_publication_table.csv"
    return load_csv(str(p)) if p.exists() else pd.DataFrame()


def density_table() -> pd.DataFrame:
    p = DENSITY_DIR / "density_uniform_publication_table.csv"
    return load_csv(str(p)) if p.exists() else pd.DataFrame()


def dataframe_download(df: pd.DataFrame, name: str, key: str):
    st.download_button(
        "Download CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=name,
        mime="text/csv",
        key=key,
    )


CORR = correctness_table()
PERF = performance_files()
COLD = cold_table()
DENS = density_table()
ALL_FILES = all_result_files()


# ---------- Sidebar ----------
with st.sidebar:
    st.markdown("## ⚡ COMET-Wasm")
    st.caption("Research Observatory")
    st.markdown(
        '<span class="badge">WebAssembly</span><span class="badge">Multi-tenant AI</span>',
        unsafe_allow_html=True,
    )
    st.write("")
    page = st.radio(
        "Explore",
        [
            "Executive Overview",
            "Correctness",
            "Performance",
            "Cold Start",
            "Tenant Density",
            "All Results",
            "Research Findings",
        ],
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown("**Execution backends**")
    st.caption("🐍 Python reference")
    st.caption("⚡ Wasmtime / WebAssembly")
    st.caption("🐳 Docker")
    st.divider()
    st.link_button("GitHub Repository ↗", REPO_URL, use_container_width=True)
    st.caption(f"{len(ALL_FILES)} CSV/JSON result files detected")


# ---------- Pages ----------
if page == "Executive Overview":
    st.markdown(
        """
        <div class="hero">
          <h1>COMET-Wasm Experimental Observatory</h1>
          <p>Evidence-driven comparison of WebAssembly and Docker for multi-tenant AI inference:
          correctness, throughput, tail latency, cold-start overhead and tenant density.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    models = len(CORR)
    equiv = int(CORR["Equivalent"].fillna(False).sum()) if not CORR.empty else 0
    cold_models = len(COLD) if not COLD.empty else 0
    dens_models = len(DENS) if not DENS.empty else 0

    a,b,c,d,e = st.columns(5)
    a.metric("Validated models", models)
    b.metric("Backend-equivalent", f"{equiv}/{models}" if models else "—")
    c.metric("Performance models", len(PERF))
    d.metric("Cold-start models", cold_models)
    e.metric("Density models", dens_models)

    st.subheader("Experiment coverage")
    known = sorted(set(CORR["Model"].tolist() if not CORR.empty else []) |
                   set(PERF.keys()) |
                   set(COLD["Model"].astype(str).tolist() if "Model" in COLD else []) |
                   set(DENS["Model"].astype(str).tolist() if "Model" in DENS else []))
    coverage = []
    for m in known:
        coverage.append({
            "Model": m,
            "Correctness": "✓" if (not CORR.empty and m in set(CORR["Model"])) else "—",
            "Performance": "✓" if m in PERF else "—",
            "Cold start": "✓" if (not COLD.empty and m in set(COLD["Model"])) else "—",
            "Density": "✓" if (not DENS.empty and m in set(DENS["Model"])) else "—",
        })
    if coverage:
        st.dataframe(pd.DataFrame(coverage), hide_index=True, use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Cold-start advantage")
        if not COLD.empty and {"Model","Docker/Wasmtime Startup"}.issubset(COLD.columns):
            fig = px.bar(
                COLD.sort_values("Docker/Wasmtime Startup", ascending=True),
                x="Docker/Wasmtime Startup", y="Model", orientation="h",
                labels={"Docker/Wasmtime Startup":"Docker / Wasmtime startup ratio (×)"},
                color="Docker/Wasmtime Startup",
                color_continuous_scale=["#3247A8","#6C63FF","#9D97FF"],
            )
            fig.update_layout(**PLOTLY_LAYOUT, coloraxis_showscale=False, title="Startup speed advantage")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Cold-start publication table not detected.")

    with col2:
        st.subheader("Memory-density advantage @ 200 tenants")
        if not DENS.empty and {"Model","Docker/Wasm @200"}.issubset(DENS.columns):
            fig = px.bar(
                DENS.sort_values("Docker/Wasm @200", ascending=True),
                x="Docker/Wasm @200", y="Model", orientation="h",
                labels={"Docker/Wasm @200":"Docker / Wasm PSS ratio (×)"},
                color="Docker/Wasm @200",
                color_continuous_scale=["#136DA5","#2496ED","#7FC8FF"],
            )
            fig.update_layout(**PLOTLY_LAYOUT, coloraxis_showscale=False, title="PSS efficiency advantage")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Density publication table not detected.")

    st.subheader("Current evidence at a glance")
    if not CORR.empty and CORR["Equivalent"].fillna(False).all():
        st.markdown('<div class="finding"><b>Correctness:</b> all loaded model-validation records preserve cross-backend equivalence.</div>', unsafe_allow_html=True)
    if not COLD.empty and "Docker/Wasmtime Startup" in COLD:
        lo = pd.to_numeric(COLD["Docker/Wasmtime Startup"], errors="coerce").min()
        hi = pd.to_numeric(COLD["Docker/Wasmtime Startup"], errors="coerce").max()
        st.markdown(f'<div class="finding"><b>Cold start:</b> Wasmtime startup is approximately <b>{lo:.2f}×–{hi:.2f}× faster</b> than Docker across the publication-table models.</div>', unsafe_allow_html=True)
    if not DENS.empty and "Docker/Wasm @200" in DENS:
        lo = pd.to_numeric(DENS["Docker/Wasm @200"], errors="coerce").min()
        hi = pd.to_numeric(DENS["Docker/Wasm @200"], errors="coerce").max()
        st.markdown(f'<div class="finding"><b>Density:</b> at 200 tenants, Docker PSS is approximately <b>{lo:.2f}×–{hi:.2f}× higher</b> than Wasm.</div>', unsafe_allow_html=True)


elif page == "Correctness":
    st.title("Correctness & Semantic Equivalence")
    st.caption("Prediction behavior is validated before performance comparisons are interpreted.")

    if CORR.empty:
        st.warning("No standard model correctness JSON files detected.")
    else:
        m = st.selectbox("Model", CORR["Model"].tolist())
        row = CORR[CORR["Model"] == m].iloc[0]

        a,b,c,d,e = st.columns(5)
        a.metric("Dataset", str(row["Dataset"]))
        b.metric("Samples", int(row["Samples"]) if pd.notna(row["Samples"]) else "—")
        c.metric("Python accuracy", fmt_num(row["Python"],4))
        d.metric("Wasmtime accuracy", fmt_num(row["Wasmtime"],4))
        e.metric("Docker accuracy", fmt_num(row["Docker"],4))

        acc = pd.DataFrame({
            "Backend":["Python","Wasmtime","Docker"],
            "Accuracy":[row["Python"],row["Wasmtime"],row["Docker"]],
        }).dropna()
        fig = px.bar(
            acc, x="Backend", y="Accuracy", text="Accuracy",
            color="Backend",
            color_discrete_map={"Python":PYTHON,"Wasmtime":WASM,"Docker":DOCKER},
            range_y=[max(0, float(acc["Accuracy"].min())-0.06), 1.01],
        )
        fig.update_traces(texttemplate="%{text:.4f}", textposition="outside")
        fig.update_layout(**PLOTLY_LAYOUT, title=f"{m}: backend accuracy")
        st.plotly_chart(fig, use_container_width=True)

        failures = pd.DataFrame({
            "Comparison":["Python ↔ Wasmtime","Python ↔ Docker","Wasmtime ↔ Docker"],
            "Prediction disagreements":[
                row["Python↔Wasmtime failures"],
                row["Python↔Docker failures"],
                row["Wasmtime↔Docker failures"],
            ],
        })
        c1,c2 = st.columns([1,2])
        with c1:
            st.metric("Cross-backend equivalent", "YES" if bool(row["Equivalent"]) else "NO")
            st.dataframe(failures, hide_index=True, use_container_width=True)
        with c2:
            fig = px.bar(
                failures, x="Comparison", y="Prediction disagreements",
                color="Comparison",
                color_discrete_sequence=[WASM,DOCKER,"#9CA3AF"],
            )
            fig.update_layout(**PLOTLY_LAYOUT, title="Disagreement audit", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("All validated models")
        display = CORR.copy()
        for col in ["Python","Wasmtime","Docker"]:
            display[col] = pd.to_numeric(display[col], errors="coerce").round(4)
        st.dataframe(display, hide_index=True, use_container_width=True)
        dataframe_download(display, "comet_wasm_correctness_summary.csv", "dl-correctness")


elif page == "Performance":
    st.title("Throughput & Tail Latency")
    st.caption("Wasmtime and Docker under matched concurrent request load.")

    if not PERF:
        st.warning("No final performance-comparison CSV files detected.")
    else:
        model = st.selectbox("Model", list(PERF.keys()))
        raw = load_csv(str(PERF[model]))
        s = perf_schema(raw)

        conc = numeric(raw, s["conc"])
        wrps = numeric(raw, s["wrps"])
        drps = numeric(raw, s["drps"])
        ratio = numeric(raw, s["ratio"])
        wp95 = numeric(raw, s["wp95"])
        dp95 = numeric(raw, s["dp95"])
        wp99 = numeric(raw, s["wp99"])
        dp99 = numeric(raw, s["dp99"])

        a,b,c,d = st.columns(4)
        a.metric("Peak Wasmtime", fmt_num(wrps.max(),0," req/s") if not wrps.empty else "—")
        b.metric("Peak Docker", fmt_num(drps.max(),0," req/s") if not drps.empty else "—")
        c.metric("Max throughput ratio", fmt_num(ratio.max(),2,"×") if not ratio.empty else "—")
        if not wp95.empty and not dp95.empty:
            aligned = pd.DataFrame({"w":wp95,"d":dp95}).dropna()
            p95_red = ((aligned["d"]-aligned["w"])/aligned["d"]*100).max() if not aligned.empty else float("nan")
            d.metric("Best P95 reduction", fmt_num(p95_red,1,"%"))
        else:
            d.metric("Best P95 reduction","—")

        if s["conc"] and s["wrps"] and s["drps"]:
            plot = pd.DataFrame({
                "Concurrency":conc,
                "Wasmtime":wrps,
                "Docker":drps,
            }).melt("Concurrency", var_name="Backend", value_name="Throughput (req/s)")
            fig = px.line(
                plot, x="Concurrency", y="Throughput (req/s)", color="Backend",
                markers=True, color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER},
            )
            fig.update_layout(**PLOTLY_LAYOUT, title=f"{model}: throughput scaling")
            st.plotly_chart(fig, use_container_width=True)

        c1,c2 = st.columns(2)
        with c1:
            if s["conc"] and s["wp95"] and s["dp95"]:
                plot = pd.DataFrame({
                    "Concurrency":conc,
                    "Wasmtime":wp95,
                    "Docker":dp95,
                }).melt("Concurrency", var_name="Backend", value_name="P95 latency (ms)")
                fig = px.line(plot,x="Concurrency",y="P95 latency (ms)",color="Backend",
                              markers=True,color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
                fig.update_layout(**PLOTLY_LAYOUT, title="P95 tail latency")
                st.plotly_chart(fig,use_container_width=True)

        with c2:
            if s["conc"] and s["wp99"] and s["dp99"]:
                plot = pd.DataFrame({
                    "Concurrency":conc,
                    "Wasmtime":wp99,
                    "Docker":dp99,
                }).melt("Concurrency", var_name="Backend", value_name="P99 latency (ms)")
                fig = px.line(plot,x="Concurrency",y="P99 latency (ms)",color="Backend",
                              markers=True,color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
                fig.update_layout(**PLOTLY_LAYOUT, title="P99 tail latency")
                st.plotly_chart(fig,use_container_width=True)

        if s["conc"] and s["ratio"]:
            rdf = pd.DataFrame({"Concurrency":conc,"Wasmtime / Docker throughput":ratio})
            fig = px.bar(
                rdf, x="Concurrency", y="Wasmtime / Docker throughput",
                text="Wasmtime / Docker throughput",
                color="Wasmtime / Docker throughput",
                color_continuous_scale=["#343D87","#6C63FF","#B5B0FF"],
            )
            fig.add_hline(y=1.0,line_dash="dash",line_color="#FFFFFF",
                          annotation_text="Parity (1×)")
            fig.update_traces(texttemplate="%{text:.2f}×",textposition="outside")
            fig.update_layout(**PLOTLY_LAYOUT, coloraxis_showscale=False,
                              title="Relative throughput advantage")
            st.plotly_chart(fig,use_container_width=True)

        st.subheader("Processed comparison data")
        st.dataframe(raw, hide_index=True, use_container_width=True)
        dataframe_download(raw, PERF[model].name, f"dl-perf-{model}")


elif page == "Cold Start":
    st.title("Cold-Start Behavior")
    st.caption("Startup and cold-to-result overhead across all completed model workloads.")

    if COLD.empty:
        st.warning("`cold_start_publication_table.csv` is not available.")
    else:
        startup_w = "Wasmtime Startup (ms)"
        startup_d = "Docker Startup (ms)"
        ratio_c = "Docker/Wasmtime Startup"
        result_w = "Wasmtime Cold-to-Result (ms)"
        result_d = "Docker Cold-to-Result (ms)"

        a,b,c,d = st.columns(4)
        a.metric("Fastest Wasmtime startup", fmt_num(pd.to_numeric(COLD[startup_w]).min(),3," ms"))
        b.metric("Fastest Docker startup", fmt_num(pd.to_numeric(COLD[startup_d]).min(),3," ms"))
        c.metric("Mean startup advantage", fmt_num(pd.to_numeric(COLD[ratio_c]).mean(),2,"×"))
        d.metric("Models measured", len(COLD))

        long = COLD.melt(
            id_vars="Model", value_vars=[startup_w,startup_d],
            var_name="Backend", value_name="Startup (ms)"
        )
        long["Backend"] = long["Backend"].map({startup_w:"Wasmtime",startup_d:"Docker"})
        fig = px.bar(
            long,x="Model",y="Startup (ms)",color="Backend",barmode="group",
            color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER},
        )
        fig.update_layout(**PLOTLY_LAYOUT,title="Startup latency by model")
        st.plotly_chart(fig,use_container_width=True)

        c1,c2 = st.columns(2)
        with c1:
            fig = px.bar(
                COLD.sort_values(ratio_c,ascending=True),
                x=ratio_c,y="Model",orientation="h",text=ratio_c,
                color=ratio_c,color_continuous_scale=["#3C348F","#6C63FF","#AAA5FF"],
            )
            fig.update_traces(texttemplate="%{text:.2f}×")
            fig.update_layout(**PLOTLY_LAYOUT,coloraxis_showscale=False,title="Docker / Wasmtime startup ratio")
            st.plotly_chart(fig,use_container_width=True)
        with c2:
            long2 = COLD.melt(
                id_vars="Model",value_vars=[result_w,result_d],
                var_name="Backend",value_name="Cold-to-result (ms)"
            )
            long2["Backend"] = long2["Backend"].map({result_w:"Wasmtime",result_d:"Docker"})
            fig = px.bar(long2,x="Model",y="Cold-to-result (ms)",color="Backend",barmode="group",
                         color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
            fig.update_layout(**PLOTLY_LAYOUT,title="End-to-end cold-to-result")
            st.plotly_chart(fig,use_container_width=True)

        st.dataframe(COLD,hide_index=True,use_container_width=True)
        dataframe_download(COLD,"cold_start_publication_table.csv","dl-cold")

        analysis = COLD_DIR / "cold_start_final_analysis.json"
        if analysis.exists():
            with st.expander("Full cold-start statistical analysis"):
                st.json(load_json(str(analysis)))


elif page == "Tenant Density":
    st.title("Multi-Tenant Memory Density")
    st.caption("Proportional Set Size (PSS) scaling as tenant count increases.")

    if DENS.empty:
        st.warning("`density_uniform_publication_table.csv` is not available.")
    else:
        a,b,c,d = st.columns(4)
        a.metric("Models measured",len(DENS))
        a200 = pd.to_numeric(DENS["Docker/Wasm @200"],errors="coerce")
        b.metric("Mean Docker/Wasm @200",fmt_num(a200.mean(),2,"×"))
        wg = pd.to_numeric(DENS["Wasm Growth (MiB/tenant)"],errors="coerce")
        dg = pd.to_numeric(DENS["Docker Growth (MiB/tenant)"],errors="coerce")
        c.metric("Mean Wasm growth",fmt_num(wg.mean(),4," MiB/tenant"))
        d.metric("Mean Docker growth",fmt_num(dg.mean(),3," MiB/tenant"))

        tenant_levels = [20,100,200]
        rows = []
        for _,r in DENS.iterrows():
            for n in tenant_levels:
                rows.append({"Model":r["Model"],"Tenants":n,"Backend":"Wasm",
                             "PSS (MiB)":r[f"Wasm PSS @{n} (MiB)"]})
                rows.append({"Model":r["Model"],"Tenants":n,"Backend":"Docker",
                             "PSS (MiB)":r[f"Docker PSS @{n} (MiB)"]})
        mem = pd.DataFrame(rows)

        fig = px.line(
            mem.groupby(["Tenants","Backend"],as_index=False)["PSS (MiB)"].mean(),
            x="Tenants",y="PSS (MiB)",color="Backend",markers=True,
            color_discrete_map={"Wasm":WASM,"Docker":DOCKER},
        )
        fig.update_layout(**PLOTLY_LAYOUT,title="Mean PSS scaling across models")
        st.plotly_chart(fig,use_container_width=True)

        c1,c2 = st.columns(2)
        with c1:
            fig = px.bar(
                DENS.sort_values("Docker/Wasm @200",ascending=True),
                x="Docker/Wasm @200",y="Model",orientation="h",text="Docker/Wasm @200",
                color="Docker/Wasm @200",color_continuous_scale=["#0C5F91","#2496ED","#7CC8FF"],
            )
            fig.update_traces(texttemplate="%{text:.2f}×")
            fig.update_layout(**PLOTLY_LAYOUT,coloraxis_showscale=False,title="PSS ratio at 200 tenants")
            st.plotly_chart(fig,use_container_width=True)
        with c2:
            growth = DENS[["Model","Wasm Growth (MiB/tenant)","Docker Growth (MiB/tenant)"]].melt(
                "Model",var_name="Backend",value_name="Growth (MiB/tenant)"
            )
            growth["Backend"] = growth["Backend"].str.replace(" Growth (MiB/tenant)","",regex=False)
            fig = px.bar(growth,x="Model",y="Growth (MiB/tenant)",color="Backend",barmode="group",
                         color_discrete_map={"Wasm":WASM,"Docker":DOCKER})
            fig.update_layout(**PLOTLY_LAYOUT,title="Incremental memory cost per tenant")
            st.plotly_chart(fig,use_container_width=True)

        st.dataframe(DENS,hide_index=True,use_container_width=True)
        dataframe_download(DENS,"density_uniform_publication_table.csv","dl-density")

        analysis = DENSITY_DIR / "density_uniform_final_analysis.json"
        if analysis.exists():
            with st.expander("Full density statistical analysis"):
                st.json(load_json(str(analysis)))


elif page == "All Results":
    st.title("Complete Result Explorer")
    st.caption("Every committed CSV and JSON file under `results/` is accessible here.")

    if not ALL_FILES:
        st.warning("No CSV/JSON result files detected.")
    else:
        rels = [str(p.relative_to(ROOT)) for p in ALL_FILES]
        category_options = ["All"] + sorted(set(
            str(p.relative_to(RESULTS).parts[0]) for p in ALL_FILES
        ))
        category = st.selectbox("Top-level result category",category_options)

        filtered = ALL_FILES
        if category != "All":
            filtered = [p for p in ALL_FILES if p.relative_to(RESULTS).parts[0] == category]

        query = st.text_input("Filter filenames",placeholder="e.g. random_forest, density, cold_start")
        if query:
            q = query.lower()
            filtered = [p for p in filtered if q in str(p.relative_to(ROOT)).lower()]

        st.caption(f"{len(filtered)} matching file(s)")
        if filtered:
            chosen_rel = st.selectbox("Result file",[str(p.relative_to(ROOT)) for p in filtered])
            chosen = ROOT / chosen_rel

            st.code(chosen_rel,language=None)
            if chosen.suffix.lower() == ".csv":
                df = load_csv(str(chosen))
                st.dataframe(df,hide_index=True,use_container_width=True)
                dataframe_download(df,chosen.name,f"dl-all-{chosen.name}")

                nums = df.select_dtypes(include="number")
                if len(nums.columns) >= 2 and len(df) > 1:
                    with st.expander("Quick numeric visualization"):
                        x = st.selectbox("X axis",list(nums.columns),key="all-x")
                        ys = st.multiselect("Y axis",[c for c in nums.columns if c != x],
                                            default=[c for c in nums.columns if c != x][:2],key="all-y")
                        if ys:
                            tmp = df[[x]+ys].melt(x,var_name="Series",value_name="Value")
                            fig = px.line(tmp,x=x,y="Value",color="Series",markers=True)
                            fig.update_layout(**PLOTLY_LAYOUT)
                            st.plotly_chart(fig,use_container_width=True)
            else:
                st.json(load_json(str(chosen)))


elif page == "Research Findings":
    st.title("Research Findings & Publication View")
    st.caption("Concise statements generated from the finalized result tables currently committed to the repository.")

    if not CORR.empty:
        n = len(CORR)
        e = int(CORR["Equivalent"].fillna(False).sum())
        st.markdown(
            f'<div class="finding"><b>Semantic preservation.</b> '
            f'{e} of {n} standard model correctness records report complete Python–Wasmtime–Docker equivalence.</div>',
            unsafe_allow_html=True,
        )

    if not COLD.empty:
        r = pd.to_numeric(COLD["Docker/Wasmtime Startup"],errors="coerce")
        best = COLD.loc[r.idxmax()]
        worst = COLD.loc[r.idxmin()]
        st.markdown(
            f'<div class="finding"><b>Cold-start result.</b> '
            f'Wasmtime reduces startup overhead by a factor of {r.min():.2f}×–{r.max():.2f}× across the measured models. '
            f'The largest relative advantage is observed for {best["Model"]} ({float(best["Docker/Wasmtime Startup"]):.2f}×).</div>',
            unsafe_allow_html=True,
        )

    if not DENS.empty:
        ratio = pd.to_numeric(DENS["Docker/Wasm @200"],errors="coerce")
        wg = pd.to_numeric(DENS["Wasm Growth (MiB/tenant)"],errors="coerce")
        dg = pd.to_numeric(DENS["Docker Growth (MiB/tenant)"],errors="coerce")
        st.markdown(
            f'<div class="finding"><b>Tenant-density result.</b> '
            f'At 200 tenants, Docker consumes {ratio.min():.2f}×–{ratio.max():.2f}× the PSS of the Wasm configuration. '
            f'Mean incremental memory growth is {wg.mean():.4f} MiB/tenant for Wasm versus {dg.mean():.3f} MiB/tenant for Docker.</div>',
            unsafe_allow_html=True,
        )

    # Cross-model performance summary
    perf_rows = []
    for model,p in PERF.items():
        try:
            df = load_csv(str(p))
            s = perf_schema(df)
            rr = numeric(df,s["ratio"])
            wr = numeric(df,s["wrps"])
            dr = numeric(df,s["drps"])
            if not rr.empty:
                perf_rows.append({
                    "Model":model,
                    "Max throughput ratio (×)":rr.max(),
                    "Mean throughput ratio (×)":rr.mean(),
                    "Peak Wasmtime RPS":wr.max() if not wr.empty else None,
                    "Peak Docker RPS":dr.max() if not dr.empty else None,
                })
        except Exception:
            pass

    if perf_rows:
        summary = pd.DataFrame(perf_rows).sort_values("Max throughput ratio (×)",ascending=False)
        st.subheader("Cross-model performance summary")
        st.dataframe(summary,hide_index=True,use_container_width=True)
        fig = px.bar(summary,x="Model",y="Max throughput ratio (×)",
                     color="Max throughput ratio (×)",
                     color_continuous_scale=["#343D87","#6C63FF","#B5B0FF"])
        fig.add_hline(y=1,line_dash="dash",line_color="#FFFFFF")
        fig.update_layout(**PLOTLY_LAYOUT,coloraxis_showscale=False,
                          title="Maximum observed Wasmtime/Docker throughput ratio")
        st.plotly_chart(fig,use_container_width=True)

    st.info(
        "These statements summarize the currently committed data. "
        "Interpretation for the final paper should preserve the experiment's confidence-interval, "
        "load-generation and hardware-control methodology."
    )


st.divider()
st.caption(
    "COMET-Wasm • Scalable multi-tenant AI inference with WebAssembly • "
    "Dashboard reads directly from committed experimental result files"
)
