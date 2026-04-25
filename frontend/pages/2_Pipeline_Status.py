"""SpendSense Streamlit Frontend — Pipeline Status & Monitoring Page."""

import base64
import os
import subprocess

import pandas as pd
import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
MLFLOW_URL = os.environ.get("MLFLOW_URL", "http://localhost:5000")
AIRFLOW_URL = os.environ.get("AIRFLOW_URL", "http://localhost:8080")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3001")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "http://localhost:9091")
ALERTMANAGER_URL = os.environ.get("ALERTMANAGER_URL", "http://localhost:9093")

st.set_page_config(page_title="Pipeline Status — SpendSense", page_icon="⚙️", layout="wide")

st.title("⚙️ ML Pipeline Status & Monitoring")
st.markdown("Real-time health and observability across the full MLOps stack.")
st.divider()

# ── Service Health (7 services) ───────────────────────────────────────────────
st.subheader("🩺 Service Health")

services = [
    ("FastAPI Backend",    f"{BACKEND_URL}/health",        "8000", BACKEND_URL),
    ("MLflow Tracking",    f"{MLFLOW_URL}/health",          "5000", MLFLOW_URL),
    ("Airflow",            f"{AIRFLOW_URL}/health",          "8080", AIRFLOW_URL),
    ("Grafana",            f"{GRAFANA_URL}/api/health",      "3001", GRAFANA_URL),
    ("Prometheus",         f"{PROMETHEUS_URL}/-/healthy",    "9090", PROMETHEUS_URL),
    ("Pushgateway",        f"{PUSHGATEWAY_URL}/-/healthy",   "9091", PUSHGATEWAY_URL),
    ("AlertManager",       f"{ALERTMANAGER_URL}/-/healthy",  "9093", ALERTMANAGER_URL),
]

# Render in two rows: 4 + 3
for row_services in [services[:4], services[4:]]:
    cols = st.columns(len(row_services))
    for col, (name, url, port, ui_url) in zip(cols, row_services):
        with col:
            try:
                resp = requests.get(url, timeout=2)
                if resp.status_code in (200, 302):
                    st.success(f"✅ **{name}**\nPort `{port}` — Online")
                else:
                    st.warning(f"⚠️ **{name}**\nHTTP `{resp.status_code}`")
            except requests.exceptions.RequestException:
                st.error(f"❌ **{name}**\nUnreachable")

st.divider()

# ── Architecture Diagram ──────────────────────────────────────────────────────
st.subheader("🏗️ System Architecture")

ARCH_DOT = """
digraph SpendSense {
    rankdir=TB
    node [shape=box style="rounded,filled" fontsize=10 margin=0.15]
    edge [fontsize=9]
    splines=ortho

    subgraph cluster_cicd {
        label="CI/CD  (GitHub Actions)" color="#9ca3af" style=dashed fontsize=11
        Job1 [label="Job 1\\nLint & Tests" fillcolor="#e5e7eb"]
        Job2 [label="Job 2\\nML Pipeline" fillcolor="#e5e7eb"]
        Job3 [label="Job 3\\nApp Deploy"  fillcolor="#e5e7eb"]
        Job1 -> Job2 -> Job3
    }

    subgraph cluster_data {
        label="Data Layer" color="#d97706" style=dashed fontsize=11
        D90   [label="90% Baseline\\ndata/raw/" fillcolor="#fef3c7"]
        D10   [label="10% Drift Data\\ndata/drift/" fillcolor="#fef3c7"]
        DFB   [label="feedback.jsonl" fillcolor="#fef3c7"]
        DIngested [label="data/ingested/" fillcolor="#fef3c7"]
    }

    subgraph cluster_dvc {
        label="DVC Pipeline" color="#059669" style=dashed fontsize=11
        DVC1 [label="ingest"     fillcolor="#d1fae5"]
        DVC2 [label="preprocess" fillcolor="#d1fae5"]
        DVC3 [label="train\\n(BiLSTM)" fillcolor="#d1fae5"]
        DVC4 [label="evaluate"   fillcolor="#d1fae5"]
        DVC1 -> DVC2 -> DVC3 -> DVC4
    }

    subgraph cluster_orchestration {
        label="Orchestration" color="#7c3aed" style=dashed fontsize=11
        AF  [label="Airflow :8080"  fillcolor="#ede9fe"]
        MLF [label="MLflow  :5000"  fillcolor="#ede9fe"]
    }

    subgraph cluster_serve {
        label="Serving Layer" color="#1d4ed8" style=dashed fontsize=11
        API [label="FastAPI\\n:8000"    fillcolor="#dbeafe"]
        UI  [label="Streamlit\\n:8501"  fillcolor="#dbeafe"]
    }

    subgraph cluster_monitoring {
        label="Monitoring" color="#be185d" style=dashed fontsize=11
        PR  [label="Prometheus\\n:9090"    fillcolor="#fce7f3"]
        PG  [label="Pushgateway\\n:9091"   fillcolor="#fce7f3"]
        GR  [label="Grafana\\n:3001"       fillcolor="#fce7f3"]
        AM  [label="AlertManager\\n:9093"  fillcolor="#fce7f3"]
    }

    Job2 -> D90
    Job2 -> D10
    D90 -> DVC1
    DVC1 -> DIngested
    DVC3 -> MLF    [label="log run-1"]
    DVC3 -> API    [label="model v1"]
    DVC4 -> MLF    [label="metrics"]
    AF -> D10      [label="polls drift\\n@daily"]
    D10 -> DVC3    [label="+ 10% (finetune)"]
    DFB -> DVC3    [label="+ corrections"]
    DVC3 -> API    [label="model v2"]
    UI  -> API     [label="REST"]
    API -> PG      [label="push metrics"]
    PG  -> PR
    PR  -> GR
    PR  -> AM
    API -> MLF     [label="list runs"]
}
"""

st.graphviz_chart(ARCH_DOT)

st.divider()

# ── HLD Pipeline Diagram ──────────────────────────────────────────────────────
st.subheader("🔀 High-Level Data Pipeline")

HLD_DOT = """
digraph HLD {
    rankdir=LR
    node [shape=box style="rounded,filled" fontsize=10]
    edge [fontsize=9]

    Raw [label="Raw Data\\n(transactions.csv)" fillcolor="#fef3c7"]
    Ingest [label="Ingest\\n(validate schema)" fillcolor="#d1fae5"]
    Preprocess [label="Preprocess\\n(tokenise + split)" fillcolor="#d1fae5"]
    Train [label="Train BiLSTM\\n(MLflow tracked)" fillcolor="#d1fae5"]
    Eval  [label="Evaluate\\n(F1 / CM / metrics)" fillcolor="#d1fae5"]
    Registry [label="MLflow Registry\\n(Staging → Prod)" fillcolor="#ede9fe"]
    Serve [label="FastAPI\\n(hot-swap)" fillcolor="#dbeafe"]
    Monitor [label="Prometheus +\\nGrafana" fillcolor="#fce7f3"]
    Drift [label="Drift Check\\n(Airflow @daily)" fillcolor="#fef3c7"]
    Retrain [label="Fine-tune\\n(1 epoch, 90%+10%+FB)" fillcolor="#d1fae5"]

    Raw -> Ingest -> Preprocess -> Train -> Eval -> Registry -> Serve
    Serve -> Monitor
    Monitor -> Drift [label="feedback\\nsamples"]
    Drift -> Retrain [label="drift\\ndetected"]
    Retrain -> Registry
}
"""

st.graphviz_chart(HLD_DOT)

st.divider()

# ── Prometheus Metrics Preview ────────────────────────────────────────────────
st.subheader("📊 Live Prometheus Metrics")
if st.button("🔄 Refresh Metrics"):
    st.rerun()

try:
    resp = requests.get(f"{BACKEND_URL}/metrics", timeout=3)
    lines = resp.text.splitlines()
    display = [
        line for line in lines
        if not line.startswith("#") and any(key in line for key in [
            "spendsense_requests_total",
            "spendsense_request_latency",
            "spendsense_predictions_by_category",
            "spendsense_model_loaded",
            "spendsense_feedback_total",
            "spendsense_drift_score",
        ])
    ]
    if display:
        st.code("\n".join(display[:40]), language="text")
    else:
        st.info("No SpendSense metrics yet — make some predictions first.")
except requests.exceptions.RequestException:
    st.error("Could not reach the backend metrics endpoint.")

st.divider()

# ── Service Dashboard Links ───────────────────────────────────────────────────
st.subheader("🔗 MLOps Service Dashboards")

link_data = [
    ("FastAPI Swagger UI",   BACKEND_URL + "/docs",         "Interactive API docs & testing"),
    ("MLflow Tracking UI",   MLFLOW_URL,                    "Experiments, runs, model registry"),
    ("Apache Airflow UI",    AIRFLOW_URL,                   "DAG runs, task logs, manual triggers"),
    ("Grafana Dashboard",    GRAFANA_URL,                   "Real-time metrics & alert panels"),
    ("Prometheus UI",        PROMETHEUS_URL,                "Raw metrics, targets & rules"),
    ("Pushgateway UI",       PUSHGATEWAY_URL,               "Batch job metrics"),
    ("AlertManager UI",      ALERTMANAGER_URL,              "Active alerts & silences"),
]

link_cols = st.columns(3)
for i, (name, url, desc) in enumerate(link_data):
    with link_cols[i % 3]:
        st.markdown(f"**{name}**")
        st.markdown(f"{desc}")
        st.markdown(f"🔗 [{url}]({url})")
        st.write("")

st.divider()

# ── DVC Pipeline Stages ───────────────────────────────────────────────────────
st.subheader("🔁 DVC Pipeline Stages")

stages = [
    ("ingest",     "Schema + null + category validation", "src/data/ingest.py",       "data/ingested/"),
    ("preprocess", "Tokenise, build vocab, split",        "src/data/preprocess.py",   "data/processed/"),
    ("train",      "Train BiLSTM + MLflow logging",       "src/models/train.py",      "models/latest_model.pt"),
    ("evaluate",   "Test-set evaluation + metrics",       "src/models/evaluate.py",   "metrics/eval_metrics.json"),
]

for i, (name, desc, script, output) in enumerate(stages):
    with st.expander(f"Stage {i + 1}: `{name}` — {desc}"):
        st.markdown(f"- **Script:** `{script}`")
        st.markdown(f"- **Output:** `{output}`")
        st.markdown(f"- **Run:** `dvc repro {name}`")

st.info("Run **`dvc repro`** to execute the full pipeline. "
        "GitHub Actions triggers this automatically on push to `main`.")

st.divider()

# ── DVC DAG Visualization ─────────────────────────────────────────────────────
_DAG_FALLBACK = """
     +--------+
     | ingest |
     +--------+
          *
    +-----------+
    | preprocess|
    +-----------+
          *
      +-------+
      | train |
      +-------+
          *
     +----------+
     | evaluate |
     +----------+
"""

st.subheader("🔀 DVC Pipeline DAG")
if st.button("🔄 Render DAG"):
    try:
        result = subprocess.run(
            ["dvc", "dag"],
            capture_output=True, text=True, timeout=10,
            cwd=os.environ.get("DVC_ROOT", "/app"),
        )
        dag_text = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        dag_text = ""
    st.code(dag_text if dag_text else _DAG_FALLBACK, language="text")
else:
    st.code(_DAG_FALLBACK, language="text")

st.divider()

# ── Airflow DAG Run History ───────────────────────────────────────────────────
st.subheader("📅 Airflow DAG Run History")

_AUTH = base64.b64encode(b"admin:admin").decode()

try:
    runs_resp = requests.get(
        f"{AIRFLOW_URL}/api/v1/dags/spendsense_ingestion_pipeline/dagRuns",
        headers={"Authorization": f"Basic {_AUTH}"},
        params={"order_by": "-start_date", "limit": 10},
        timeout=5,
    )
    if runs_resp.status_code == 200:
        dag_runs = runs_resp.json().get("dag_runs", [])
        if dag_runs:
            rows = []
            for run in dag_runs:
                state = run.get("state", "unknown")
                icon = "✅" if state == "success" else ("❌" if state == "failed" else "🔄")
                rows.append({
                    "Run ID": run.get("dag_run_id", ""),
                    "State": f"{icon} {state}",
                    "Start": (run.get("start_date") or "")[:19],
                    "End": (run.get("end_date") or "")[:19],
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # Show task-level breakdown for the most recent run
            latest_run_id = dag_runs[0].get("dag_run_id")
            if latest_run_id:
                with st.expander(f"Task breakdown — latest run: `{latest_run_id}`"):
                    tasks_resp = requests.get(
                        f"{AIRFLOW_URL}/api/v1/dags/spendsense_ingestion_pipeline"
                        f"/dagRuns/{latest_run_id}/taskInstances",
                        headers={"Authorization": f"Basic {_AUTH}"},
                        timeout=5,
                    )
                    if tasks_resp.status_code == 200:
                        task_instances = tasks_resp.json().get("task_instances", [])
                        task_rows = []
                        for ti in task_instances:
                            ts = ti.get("state", "unknown")
                            tico = "✅" if ts == "success" else ("❌" if ts == "failed" else "⏭️" if ts == "skipped" else "🔄")
                            task_rows.append({
                                "Task": ti.get("task_id", ""),
                                "State": f"{tico} {ts}",
                                "Duration (s)": round(ti.get("duration") or 0, 1),
                            })
                        st.dataframe(pd.DataFrame(task_rows), use_container_width=True, hide_index=True)
                    else:
                        st.warning(f"Could not fetch task instances (HTTP {tasks_resp.status_code})")
        else:
            st.info("No DAG runs found for `spendsense_ingestion_pipeline` yet.")
    elif runs_resp.status_code == 404:
        st.info("DAG `spendsense_ingestion_pipeline` not found — Airflow may not be running.")
    else:
        st.warning(f"Airflow API returned HTTP {runs_resp.status_code}")
except requests.exceptions.RequestException:
    st.error("Could not reach the Airflow API. Check that the Airflow service is running.")
