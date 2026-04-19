"""SpendSense Streamlit Frontend — Pipeline Status & Monitoring Page."""

import os

import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
MLFLOW_URL = os.environ.get("MLFLOW_URL", "http://localhost:5000")
AIRFLOW_URL = os.environ.get("AIRFLOW_URL", "http://localhost:8080")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3000")

st.set_page_config(page_title="Pipeline Status — SpendSense", page_icon="⚙️", layout="wide")

st.title("⚙️ ML Pipeline Status & Monitoring")
st.markdown("Real-time health and observability across the full MLOps stack.")
st.divider()

# ── Service Health ────────────────────────────────────────────────────────────
st.subheader("🩺 Service Health")
cols = st.columns(4)

services = [
    ("FastAPI Backend", f"{BACKEND_URL}/health", "8000"),
    ("MLflow Tracking", f"{MLFLOW_URL}/health", "5000"),
    ("Airflow Webserver", f"{AIRFLOW_URL}/health", "8080"),
    ("Grafana Dashboard", f"{GRAFANA_URL}/api/health", "3000"),
]

for col, (name, url, port) in zip(cols, services):
    with col:
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code in (200, 302):
                st.success(f"✅ **{name}**\nPort `{port}` — Online")
            else:
                st.warning(f"⚠️ **{name}**\nStatus `{resp.status_code}`")
        except requests.exceptions.RequestException:
            st.error(f"❌ **{name}**\nUnreachable")

st.divider()

# ── Prometheus Metrics Preview ────────────────────────────────────────────────
st.subheader("📊 Live Prometheus Metrics")
if st.button("🔄 Refresh Metrics"):
    st.rerun()

try:
    resp = requests.get(f"{BACKEND_URL}/metrics", timeout=3)
    lines = resp.text.splitlines()
    # Extract key metrics for display
    display = []
    for line in lines:
        if line.startswith("#"):
            continue
        if any(key in line for key in [
            "spendsense_requests_total",
            "spendsense_request_latency",
            "spendsense_error_rate",
            "spendsense_predictions_by_category",
            "spendsense_model_loaded",
        ]):
            display.append(line)

    if display:
        st.code("\n".join(display[:40]), language="text")
    else:
        st.info("No SpendSense metrics yet — make some predictions first.")
except requests.exceptions.RequestException:
    st.error("Could not reach the backend metrics endpoint.")

st.divider()

# ── External Tool Links ───────────────────────────────────────────────────────
st.subheader("🔗 MLOps Tool Dashboards")

link_cols = st.columns(3)
with link_cols[0]:
    st.markdown(f"""
    **MLflow Tracking UI**
    - Experiments, runs, parameters
    - Model registry
    - Artifact viewer

    🔗 [{MLFLOW_URL}]({MLFLOW_URL})
    """)

with link_cols[1]:
    st.markdown(f"""
    **Apache Airflow UI**
    - DAG runs and status
    - Task logs and history
    - Trigger manual runs

    🔗 [{AIRFLOW_URL}]({AIRFLOW_URL})
    """)

with link_cols[2]:
    st.markdown(f"""
    **Grafana Dashboard**
    - NRT request rate
    - Latency percentiles
    - Error rate alerts (>5%)

    🔗 [{GRAFANA_URL}]({GRAFANA_URL})
    """)

st.divider()

# ── DVC Pipeline Stages ───────────────────────────────────────────────────────
st.subheader("🔁 DVC Pipeline Stages")
st.markdown("The DVC DAG defines the reproducible ML pipeline:")

stages = [
    ("ingest", "Schema + null + category validation", "src/data/ingest.py", "data/ingested/"),
    ("preprocess", "Tokenise, build vocab, split", "src/data/preprocess.py", "data/processed/"),
    ("train", "Train BiLSTM + MLflow logging", "src/models/train.py", "models/best_model.pt"),
    ("evaluate", "Test-set evaluation + metrics", "src/models/evaluate.py",
     "metrics/eval_metrics.json"),
]

for i, (name, desc, script, output) in enumerate(stages):
    with st.expander(f"Stage {i + 1}: `{name}` — {desc}"):
        st.markdown(f"- **Script:** `{script}`")
        st.markdown(f"- **Output:** `{output}`")
        st.markdown(f"- **Run:** `dvc repro {name}`")

st.info("Run **`dvc repro`** to execute the full pipeline. "
        "GitHub Actions triggers this automatically on push to `main`.")
