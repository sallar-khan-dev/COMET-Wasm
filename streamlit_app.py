from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CORRECTNESS_DIR = RESULTS / "correctness"
PROCESSED_DIR = RESULTS / "processed"
PERF_DIR = PROCESSED_DIR / "performance"
COLD_DIR = PROCESSED_DIR / "cold_start"
DENSITY_DIR = PROCESSED_DIR / "density"
EXEC_DIR = PROCESSED_DIR / "execution_time"
OVERHEAD_DIR = PROCESSED_DIR / "overhead"
INTERFERENCE_DIR = PROCESSED_DIR / "interference"

REPO_URL = "https://github.com/sallar-khan-dev/COMET-Wasm"

st.set_page_config(
    page_title="COMET-Wasm | Research Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

WASM = "#6C63FF"
DOCKER = "#2496ED"
PYTHON = "#F2C94C"
TEXT = "#E5E7EB"
MUTED = "#94A3B8"

st.markdown(
    f"""
    <style>
    .stApp {{
      background:
        radial-gradient(circle at 12% 4%, rgba(108,99,255,.13), transparent 28%),
        radial-gradient(circle at 85% 10%, rgba(36,150,237,.10), transparent 30%),
        #07101d;
      color:{TEXT};
    }}
    [data-testid="stSidebar"] {{
      background:linear-gradient(180deg,#091322 0%,#080f1a 100%);
      border-right:1px solid rgba(148,163,184,.15);
    }}
    .block-container {{padding-top:1.2rem;max-width:1500px;}}
    .hero {{
      border:1px solid rgba(148,163,184,.18);
      background:linear-gradient(135deg,rgba(108,99,255,.16),rgba(36,150,237,.07));
      border-radius:20px;padding:1.35rem 1.55rem;margin-bottom:1rem;
    }}
    .finding {{
      border-left:4px solid {WASM};background:rgba(15,23,42,.75);
      border-radius:10px;padding:.8rem 1rem;margin:.45rem 0;
    }}
    div[data-testid="stMetric"] {{
      background:rgba(15,23,42,.72);
      border:1px solid rgba(148,163,184,.16);
      padding:.85rem;border-radius:14px;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

PLOTLY_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=TEXT),
    margin=dict(l=25,r=20,t=50,b=25),
    legend=dict(orientation="h",y=1.02,x=0),
)

CANONICAL_MODELS = [
    "Logistic Regression",
    "Gaussian Naive Bayes",
    "Decision Tree",
    "K-Means",
    "Random Forest",
    "SVM",
    "MLP",
]

def pretty_model(name: str) -> str:
    k = str(name).lower().strip().replace("-", "_").replace(" ", "_")
    aliases = {
        "logistic_regression":"Logistic Regression",
        "lr":"Logistic Regression",
        "naive_bayes":"Gaussian Naive Bayes",
        "gaussian_naive_bayes":"Gaussian Naive Bayes",
        "gnb":"Gaussian Naive Bayes",
        "decision_tree":"Decision Tree",
        "dt":"Decision Tree",
        "kmeans":"K-Means",
        "k_means":"K-Means",
        "random_forest":"Random Forest",
        "rf":"Random Forest",
        "svm":"SVM",
        "svm_rbf":"SVM",
        "rbf_svm":"SVM",
        "mlp":"MLP",
        "multilayer_perceptron":"MLP",
    }
    return aliases.get(k, str(name).replace("_"," ").replace("-"," ").title())

@st.cache_data(show_spinner=False)
def load_json(path: str) -> Any:
    with open(path,"r",encoding="utf-8") as f:
        return json.load(f)

@st.cache_data(show_spinner=False)
def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)

def fmt_num(v: Any, digits:int=2, suffix:str="") -> str:
    try:
        if pd.isna(v):
            return "—"
        return f"{float(v):,.{digits}f}{suffix}"
    except Exception:
        return "—"

def normalize_model_column(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Model" not in df.columns:
        return df
    out = df.copy()
    out["Model"] = out["Model"].map(pretty_model)
    out = out[out["Model"].isin(CANONICAL_MODELS)]
    order = {m:i for i,m in enumerate(CANONICAL_MODELS)}
    out["_order"] = out["Model"].map(order)
    return out.sort_values("_order").drop(columns="_order").reset_index(drop=True)

def publication_table(folder: Path, filename: str) -> pd.DataFrame:
    p = folder / filename
    return normalize_model_column(load_csv(str(p))) if p.exists() else pd.DataFrame()

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
        if not isinstance(d,dict) or "model" not in d:
            continue

        model = pretty_model(d.get("model",p.stem))
        if model not in CANONICAL_MODELS:
            continue

        metric_name = "Accuracy"
        metric = d.get("accuracy")
        if not isinstance(metric,dict):
            metric = d.get("agreement_with_exported_cluster_assignment")
            metric_name = "Cluster agreement"
        if not isinstance(metric,dict):
            continue

        eq = d.get("equivalence",{}) or {}
        rows.append({
            "Model":model,
            "Dataset":d.get("dataset","—"),
            "Samples":d.get("samples"),
            "Metric":metric_name,
            "Python":metric.get("python_reference"),
            "Wasmtime":metric.get("wasmtime"),
            "Docker":metric.get("docker"),
            "Equivalent":bool(eq.get("all_backends_equivalent",False)),
            "Python↔Wasmtime failures":eq.get("python_vs_wasmtime_failures",0),
            "Python↔Docker failures":eq.get("python_vs_docker_failures",0),
            "Wasmtime↔Docker failures":eq.get("wasmtime_vs_docker_failures",0),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    order = {m:i for i,m in enumerate(CANONICAL_MODELS)}
    df["_order"] = df["Model"].map(order)
    return df.sort_values("_order").drop(columns="_order").reset_index(drop=True)

def performance_files() -> dict[str,Path]:
    files = {}
    if PERF_DIR.exists():
        for p in sorted(PERF_DIR.glob("*_performance_final_comparison.csv")):
            m = pretty_model(p.name.replace("_performance_final_comparison.csv",""))
            if m in CANONICAL_MODELS:
                files[m] = p
    return {m:files[m] for m in CANONICAL_MODELS if m in files}

def all_result_files():
    if not RESULTS.exists():
        return []
    return sorted(p for p in RESULTS.rglob("*") if p.is_file() and p.suffix.lower() in {".csv",".json"})

CORR = correctness_table()
PERF = performance_files()
COLD = publication_table(COLD_DIR,"cold_start_publication_table.csv")
DENS = publication_table(DENSITY_DIR,"density_uniform_publication_table.csv")
EXEC = publication_table(EXEC_DIR,"execution_time_publication_table.csv")
OVERHEAD = publication_table(OVERHEAD_DIR,"overhead_publication_table.csv")
INTERFERENCE = load_csv(str(INTERFERENCE_DIR/"interference_publication_table.csv")) if (INTERFERENCE_DIR/"interference_publication_table.csv").exists() else pd.DataFrame()
ALL_FILES = all_result_files()

with st.sidebar:
    st.markdown("## ⚡ COMET-Wasm")
    st.caption("Research Observatory")
    page = st.radio(
        "Explore",
        ["Executive Overview","Correctness","Performance","Cold Start","Tenant Density","Execution Time","Serving Overhead","Interference","All Results","Research Findings"],
        label_visibility="collapsed",
    )
    st.divider()
    st.link_button("GitHub Repository ↗",REPO_URL,use_container_width=True)
    st.caption(f"{len(ALL_FILES)} CSV/JSON result files detected")

if page == "Executive Overview":
    st.markdown(
        '<div class="hero"><h1>COMET-Wasm Experimental Observatory</h1>'
        '<p>Evidence-driven comparison of WebAssembly and Docker for multi-tenant AI inference.</p></div>',
        unsafe_allow_html=True,
    )

    models = len(CORR)
    equiv = int(CORR["Equivalent"].fillna(False).sum()) if not CORR.empty else 0

    a,b,c,d,e,f = st.columns(6)
    a.metric("Validated models",models)
    b.metric("Backend-equivalent",f"{equiv}/{models}" if models else "—")
    c.metric("Performance models",len(PERF))
    d.metric("Cold-start models",len(COLD))
    e.metric("Density models",len(DENS))
    f.metric("Interference configs",len(INTERFERENCE) if not INTERFERENCE.empty else 0)

    coverage=[]
    for m in CANONICAL_MODELS:
        coverage.append({
            "Model":m,
            "Correctness":"✓" if m in set(CORR["Model"]) else "—",
            "Performance":"✓" if m in PERF else "—",
            "Cold start":"✓" if (not COLD.empty and m in set(COLD["Model"])) else "—",
            "Density":"✓" if (not DENS.empty and m in set(DENS["Model"])) else "—",
            "Execution time":"✓" if (not EXEC.empty and m in set(EXEC["Model"])) else "—",
            "Overhead":"✓" if (not OVERHEAD.empty and m in set(OVERHEAD["Model"])) else "—",
        })
    st.subheader("Experiment coverage")
    st.dataframe(pd.DataFrame(coverage),hide_index=True,use_container_width=True)

    c1,c2 = st.columns(2)
    with c1:
        if not COLD.empty:
            fig=px.bar(COLD.sort_values("Docker/Wasmtime Startup"),x="Docker/Wasmtime Startup",y="Model",orientation="h",color="Docker/Wasmtime Startup",color_continuous_scale=["#3247A8","#6C63FF","#9D97FF"])
            fig.update_layout(**PLOTLY_LAYOUT,coloraxis_showscale=False,title="Cold-start advantage (Docker/Wasmtime)")
            st.plotly_chart(fig,use_container_width=True)
    with c2:
        if not DENS.empty:
            fig=px.bar(DENS.sort_values("Docker/Wasm @200"),x="Docker/Wasm @200",y="Model",orientation="h",color="Docker/Wasm @200",color_continuous_scale=["#136DA5","#2496ED","#7FC8FF"])
            fig.update_layout(**PLOTLY_LAYOUT,coloraxis_showscale=False,title="Memory-density advantage @ 200 tenants")
            st.plotly_chart(fig,use_container_width=True)

    if not INTERFERENCE.empty:
        iw=INTERFERENCE[INTERFERENCE["Backend"].str.lower()=="wasmtime"]
        idk=INTERFERENCE[INTERFERENCE["Backend"].str.lower()=="docker"]
        wp=pd.to_numeric(iw["Mean P95 Degradation (%)"],errors="coerce").mean()
        dp=pd.to_numeric(idk["Mean P95 Degradation (%)"],errors="coerce").mean()
        st.markdown(f'<div class="finding"><b>Mixed-tenant interference:</b> mean P95 degradation is <b>{wp:.2f}%</b> for Wasmtime versus <b>{dp:.2f}%</b> for Docker.</div>',unsafe_allow_html=True)

elif page == "Correctness":
    st.title("Correctness & Semantic Equivalence")
    if CORR.empty:
        st.warning("No correctness records found.")
    else:
        m=st.selectbox("Model",CORR["Model"].tolist())
        row=CORR[CORR["Model"]==m].iloc[0]
        metric=str(row["Metric"])
        a,b,c,d,e=st.columns(5)
        a.metric("Dataset",row["Dataset"])
        b.metric("Samples",int(row["Samples"]) if pd.notna(row["Samples"]) else "—")
        c.metric(f"Python {metric.lower()}",fmt_num(row["Python"],4))
        d.metric(f"Wasmtime {metric.lower()}",fmt_num(row["Wasmtime"],4))
        e.metric(f"Docker {metric.lower()}",fmt_num(row["Docker"],4))
        acc=pd.DataFrame({"Backend":["Python","Wasmtime","Docker"],metric:[row["Python"],row["Wasmtime"],row["Docker"]]})
        fig=px.bar(acc,x="Backend",y=metric,text=metric,color="Backend",color_discrete_map={"Python":PYTHON,"Wasmtime":WASM,"Docker":DOCKER})
        fig.update_traces(texttemplate="%{text:.4f}",textposition="outside")
        fig.update_layout(**PLOTLY_LAYOUT,title=f"{m}: {metric.lower()} by backend")
        st.plotly_chart(fig,use_container_width=True)
        st.dataframe(CORR,hide_index=True,use_container_width=True)

elif page == "Performance":
    st.title("Throughput & Tail Latency")
    if not PERF:
        st.warning("No final performance files found.")
    else:
        m=st.selectbox("Model",list(PERF.keys()))
        df=load_csv(str(PERF[m]))
        cols={c.lower():c for c in df.columns}
        conc=cols.get("concurrency")
        wrps=cols.get("wasmtime_rps") or cols.get("throughput_rps_wasmtime")
        drps=cols.get("docker_rps") or cols.get("throughput_rps_docker")
        wp95=cols.get("wasmtime_p95_ms") or cols.get("p95_latency_ms_wasmtime")
        dp95=cols.get("docker_p95_ms") or cols.get("p95_latency_ms_docker")
        wp99=cols.get("wasmtime_p99_ms") or cols.get("p99_latency_ms_wasmtime")
        dp99=cols.get("docker_p99_ms") or cols.get("p99_latency_ms_docker")

        if conc and wrps and drps:
            plot=pd.DataFrame({"Concurrency":df[conc],"Wasmtime":df[wrps],"Docker":df[drps]}).melt("Concurrency",var_name="Backend",value_name="Throughput (req/s)")
            fig=px.line(plot,x="Concurrency",y="Throughput (req/s)",color="Backend",markers=True,color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
            fig.update_layout(**PLOTLY_LAYOUT,title=f"{m}: throughput scaling")
            st.plotly_chart(fig,use_container_width=True)

        c1,c2=st.columns(2)
        with c1:
            if conc and wp95 and dp95:
                plot=pd.DataFrame({"Concurrency":df[conc],"Wasmtime":df[wp95],"Docker":df[dp95]}).melt("Concurrency",var_name="Backend",value_name="P95 latency (ms)")
                fig=px.line(plot,x="Concurrency",y="P95 latency (ms)",color="Backend",markers=True,color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
                fig.update_layout(**PLOTLY_LAYOUT,title="P95 latency")
                st.plotly_chart(fig,use_container_width=True)
        with c2:
            if conc and wp99 and dp99:
                plot=pd.DataFrame({"Concurrency":df[conc],"Wasmtime":df[wp99],"Docker":df[dp99]}).melt("Concurrency",var_name="Backend",value_name="P99 latency (ms)")
                fig=px.line(plot,x="Concurrency",y="P99 latency (ms)",color="Backend",markers=True,color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
                fig.update_layout(**PLOTLY_LAYOUT,title="P99 latency")
                st.plotly_chart(fig,use_container_width=True)
        st.dataframe(df,hide_index=True,use_container_width=True)

elif page == "Cold Start":
    st.title("Cold-Start Behavior")
    if COLD.empty:
        st.warning("No cold-start publication table found.")
    else:
        long=COLD.melt(id_vars="Model",value_vars=["Wasmtime Startup (ms)","Docker Startup (ms)"],var_name="Backend",value_name="Startup (ms)")
        long["Backend"]=long["Backend"].map({"Wasmtime Startup (ms)":"Wasmtime","Docker Startup (ms)":"Docker"})
        fig=px.bar(long,x="Model",y="Startup (ms)",color="Backend",barmode="group",color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
        fig.update_layout(**PLOTLY_LAYOUT,title="Startup latency by model")
        st.plotly_chart(fig,use_container_width=True)
        st.dataframe(COLD,hide_index=True,use_container_width=True)

elif page == "Tenant Density":
    st.title("Multi-Tenant Memory Density")
    if DENS.empty:
        st.warning("No density publication table found.")
    else:
        rows=[]
        for _,r in DENS.iterrows():
            for n in [20,100,200]:
                rows += [
                    {"Model":r["Model"],"Tenants":n,"Backend":"Wasm","PSS (MiB)":r[f"Wasm PSS @{n} (MiB)"]},
                    {"Model":r["Model"],"Tenants":n,"Backend":"Docker","PSS (MiB)":r[f"Docker PSS @{n} (MiB)"]},
                ]
        mem=pd.DataFrame(rows)
        fig=px.line(mem.groupby(["Tenants","Backend"],as_index=False)["PSS (MiB)"].mean(),x="Tenants",y="PSS (MiB)",color="Backend",markers=True,color_discrete_map={"Wasm":WASM,"Docker":DOCKER})
        fig.update_layout(**PLOTLY_LAYOUT,title="Mean PSS scaling across models")
        st.plotly_chart(fig,use_container_width=True)
        st.dataframe(DENS,hide_index=True,use_container_width=True)

elif page == "Execution Time":
    st.title("Model Execution Time")
    st.caption("Pure model-compute time separated from serving overhead.")
    if EXEC.empty:
        st.warning("No execution-time publication table found.")
    else:
        w="Wasmtime Execution Time (us)"
        d="Docker Execution Time (us)"
        long=EXEC.melt(id_vars="Model",value_vars=[w,d],var_name="Backend",value_name="Execution time (μs)")
        long["Backend"]=long["Backend"].map({w:"Wasmtime",d:"Docker"})
        fig=px.bar(long,x="Model",y="Execution time (μs)",color="Backend",barmode="group",color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
        fig.update_layout(**PLOTLY_LAYOUT,title="Pure model execution time")
        st.plotly_chart(fig,use_container_width=True)
        st.dataframe(EXEC,hide_index=True,use_container_width=True)

elif page == "Serving Overhead":
    st.title("End-to-End Serving Overhead")
    if OVERHEAD.empty:
        st.warning("No overhead publication table found.")
    else:
        w="Wasmtime E2E (us)"
        d="Docker E2E (us)"
        long=OVERHEAD.melt(id_vars="Model",value_vars=[w,d],var_name="Backend",value_name="E2E latency (μs)")
        long["Backend"]=long["Backend"].map({w:"Wasmtime",d:"Docker"})
        fig=px.bar(long,x="Model",y="E2E latency (μs)",color="Backend",barmode="group",color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
        fig.update_layout(**PLOTLY_LAYOUT,title="End-to-end request latency")
        st.plotly_chart(fig,use_container_width=True)

        c1,c2=st.columns(2)
        with c1:
            fig=px.bar(OVERHEAD,x="Model",y="Wasmtime E2E Reduction (%)",text="Wasmtime E2E Reduction (%)",color="Wasmtime E2E Reduction (%)",color_continuous_scale=["#285B4D","#22C55E","#86EFAC"])
            fig.update_layout(**PLOTLY_LAYOUT,coloraxis_showscale=False,title="Wasmtime E2E reduction vs Docker")
            st.plotly_chart(fig,use_container_width=True)
        with c2:
            share=OVERHEAD[["Model","Wasmtime Execution Share (%)","Docker Execution Share (%)"]].melt("Model",var_name="Backend",value_name="Execution share (%)")
            share["Backend"]=share["Backend"].map({"Wasmtime Execution Share (%)":"Wasmtime","Docker Execution Share (%)":"Docker"})
            fig=px.bar(share,x="Model",y="Execution share (%)",color="Backend",barmode="group",color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
            fig.update_layout(**PLOTLY_LAYOUT,title="Model execution share of E2E latency")
            st.plotly_chart(fig,use_container_width=True)

        st.dataframe(OVERHEAD,hide_index=True,use_container_width=True)

elif page == "Interference":
    st.title("Mixed-Tenant Interference")
    st.caption("Cross-workload interference under simultaneous multi-tenant execution.")

    if INTERFERENCE.empty:
        st.warning("No interference publication table found.")
    else:
        df=INTERFERENCE.copy()
        df["Backend"]=df["Backend"].str.title()
        iw=df[df["Backend"]=="Wasmtime"]
        idk=df[df["Backend"]=="Docker"]

        a,b,c,d=st.columns(4)
        a.metric("Workload pairs",df["Pair"].nunique())
        b.metric("Backend configs",len(df))
        c.metric("Wasmtime mean P95 degradation",fmt_num(pd.to_numeric(iw["Mean P95 Degradation (%)"],errors="coerce").mean(),2,"%"))
        d.metric("Docker mean P95 degradation",fmt_num(pd.to_numeric(idk["Mean P95 Degradation (%)"],errors="coerce").mean(),2,"%"))

        fig=px.bar(df,x="Pair",y="Mean P95 Degradation (%)",color="Backend",barmode="group",color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
        fig.update_layout(**PLOTLY_LAYOUT,title="P95 degradation under mixed-tenant load")
        st.plotly_chart(fig,use_container_width=True)

        c1,c2=st.columns(2)
        with c1:
            fig=px.bar(df,x="Pair",y="Mean Throughput Degradation (%)",color="Backend",barmode="group",color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
            fig.update_layout(**PLOTLY_LAYOUT,title="Throughput degradation")
            st.plotly_chart(fig,use_container_width=True)
        with c2:
            fig=px.bar(df,x="Pair",y="Mean Mixed P99 (ms)",color="Backend",barmode="group",color_discrete_map={"Wasmtime":WASM,"Docker":DOCKER})
            fig.update_layout(**PLOTLY_LAYOUT,title="Mixed-workload P99 latency")
            st.plotly_chart(fig,use_container_width=True)

        status=df[["Pair","Backend","Repetitions","CI Pass"]].copy()
        status["CI Status"]=status["CI Pass"].map({True:"PASS",False:"MAX-REPS / CI not met"})
        st.subheader("Statistical completion status")
        st.dataframe(status.drop(columns=["CI Pass"]),hide_index=True,use_container_width=True)
        st.subheader("Publication table")
        st.dataframe(df,hide_index=True,use_container_width=True)

elif page == "All Results":
    st.title("Complete Result Explorer")
    if not ALL_FILES:
        st.warning("No result files detected.")
    else:
        chosen=st.selectbox("Result file",[str(p.relative_to(ROOT)) for p in ALL_FILES])
        p=ROOT/chosen
        if p.suffix.lower()==".csv":
            st.dataframe(load_csv(str(p)),hide_index=True,use_container_width=True)
        else:
            st.json(load_json(str(p)))

elif page == "Research Findings":
    st.title("Research Findings")

    if not CORR.empty:
        st.markdown(f'<div class="finding"><b>Correctness:</b> {int(CORR["Equivalent"].sum())}/{len(CORR)} canonical workloads preserve cross-backend equivalence.</div>',unsafe_allow_html=True)

    if not COLD.empty:
        r=pd.to_numeric(COLD["Docker/Wasmtime Startup"],errors="coerce")
        st.markdown(f'<div class="finding"><b>Cold start:</b> Wasmtime is {r.min():.2f}×–{r.max():.2f}× faster to start than Docker.</div>',unsafe_allow_html=True)

    if not DENS.empty:
        r=pd.to_numeric(DENS["Docker/Wasm @200"],errors="coerce")
        st.markdown(f'<div class="finding"><b>Density:</b> Docker uses {r.min():.2f}×–{r.max():.2f}× the Wasm PSS at 200 tenants.</div>',unsafe_allow_html=True)

    if not EXEC.empty:
        r=pd.to_numeric(EXEC["Wasm/Docker Ratio"],errors="coerce")
        st.markdown(f'<div class="finding"><b>Pure model execution:</b> Wasmtime execution time is {r.min():.2f}×–{r.max():.2f}× the Docker baseline across the seven workloads.</div>',unsafe_allow_html=True)

    if not OVERHEAD.empty:
        r=pd.to_numeric(OVERHEAD["Wasmtime E2E Reduction (%)"],errors="coerce")
        st.markdown(f'<div class="finding"><b>End-to-end serving:</b> Wasmtime reduces request latency by {r.min():.2f}%–{r.max():.2f}%.</div>',unsafe_allow_html=True)

    if not INTERFERENCE.empty:
        iw=INTERFERENCE[INTERFERENCE["Backend"].str.lower()=="wasmtime"]
        idk=INTERFERENCE[INTERFERENCE["Backend"].str.lower()=="docker"]
        wp=pd.to_numeric(iw["Mean P95 Degradation (%)"],errors="coerce").mean()
        dp=pd.to_numeric(idk["Mean P95 Degradation (%)"],errors="coerce").mean()
        wt=pd.to_numeric(iw["Mean Throughput Degradation (%)"],errors="coerce").mean()
        dt=pd.to_numeric(idk["Mean Throughput Degradation (%)"],errors="coerce").mean()
        st.markdown(f'<div class="finding"><b>Mixed-tenant interference:</b> mean P95 degradation is {wp:.2f}% for Wasmtime vs {dp:.2f}% for Docker; mean throughput degradation is {wt:.2f}% vs {dt:.2f}%.</div>',unsafe_allow_html=True)

st.divider()
st.caption("COMET-Wasm • WebAssembly vs Docker for multi-tenant AI inference")
