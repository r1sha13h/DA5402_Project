# Architecture Document — SpendSense

## System Overview

SpendSense is a neural-network-based personal expense classifier that automatically categorises bank transaction descriptions into one of 10 expense categories. The system implements a full MLOps architecture with five clearly separated layers, each with a distinct responsibility.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│              GitHub Actions  (CI/CD Orchestration Layer)             │
│  Trigger on: push to main/develop · pull_request · workflow_dispatch │
│  Job 1: lint + pytest (all branches, ~40s)                           │
│  Job 2: ML pipeline: train → Airflow drift check → fine-tune (~11m)  │
│  Job 3: artifact download → backend+frontend smoke tests (~1.5m)     │
└───────────────┬──────────────────────────┬───────────────────────────┘
                │                          │
                ▼                          ▼
┌──────────────────────────┐   ┌───────────────────────────────────────┐
│  Airflow (DAG Engine)    │   │  DVC (Reproducible ML Pipeline)       │
│  @daily · 9-task DAG     │   │  ingest → preprocess → train → eval   │
│  Validates schema, nulls │   │  params.yaml controls all stages      │
│  Detects data drift      │   │  dvc.lock pins every artifact hash    │
│  If drift: combine data  │   └──────────────┬────────────────────────┘
│  and trigger DVC repro   │                  │
└──────────────────────────┘                  │
                                              ▼
                               ┌──────────────────────────┐
                               │  MLflow Tracking Server  │
                               │  Logs every run: params, │
                               │  metrics & model weights │
                               │  Auto-promotes to Staging│
                               └──────────────┬───────────┘
                                              │
                ┌─────────────────────────────▼─────────────────────────┐
                │             docker-compose (Runtime Layer)            │
                │  ┌─────────────────┐  ┌────────────────────────────┐ │
                │  │ FastAPI Backend │  │  Streamlit Frontend        │ │
                │  │ /predict        │←─│  Home · Batch · Status     │ │
                │  │ /predict/batch  │  │  HDFC XLS · Feedback form  │ │
                │  │ /feedback       │  └────────────────────────────┘ │
                │  │ /drift          │                                  │
                │  │ /models[/switch]│                                  │
                │  │ /health /ready  │                                  │
                │  │ /metrics        │                                  │
                │  └────────┬────────┘                                  │
                │           │                                           │
                │  ┌────────▼──────────────────────────────────────┐  │
                │  │ Prometheus · Grafana · Alertmanager · Pushgateway│  │
                │  │ Real-time dashboard: 8 panels · 11 alert rules   │  │
                │  │ Alerts: HighErrorRate > 5% · DataDriftDetected   │  │
                │  │ All 5 components push or expose metrics          │  │
                │  └────────────────────────────────────────────────────┘  │
                └───────────────────────────────────────────────────────┘
```

## Layer Descriptions

### Layer 1 — GitHub Actions (Outer CI/CD Orchestrator)
- Top-level control plane; triggers on `git push` to `main`/`develop`, pull requests, and `workflow_dispatch`
- **3-job BAT pipeline** (Build → Assess → Test), total ~13 min on a self-hosted GPU runner:
  - **Job 1** (~30s): flake8 lint + 68 unit tests + 60% coverage gate — runs on every branch
  - **Job 2** (~11.5 min): 90-10 drift split → infra services up → DVC Run 1 (90% baseline) → Airflow DAG (drift detection + 90%+10%+feedback merge) → DVC Run 2 (fine-tune) — main branch only
  - **Job 3** (~1 min): restore model artifact from local stage → Docker build backend+frontend → smoke-test all API endpoints — main branch only
- Self-hosted runner — no cloud compute

### Layer 2A — Apache Airflow (Data Orchestration)
- DAG ID: `spendsense_ingestion_pipeline`, schedule `@daily`
- **9-task chain:** `verify_raw_data → validate_schema → check_nulls → check_drift → route_on_drift → [combine_data → run_ingest → trigger_dvc] / [pipeline_complete]`
- `route_on_drift` is a `BranchPythonOperator` — routes to `combine_data` when drift is detected (> 10 pp shift), else directly to `pipeline_complete`
- `combine_data` merges 90% baseline + 10% drift file + `feedback/feedback.jsonl` corrections into the combined training corpus
- All tasks push metrics to Prometheus Pushgateway
- Web UI on port 8080

### Layer 2B — DVC (ML Pipeline Reproducibility)
- Defines the ML pipeline as a DAG in `dvc.yaml`: `ingest → preprocess → train → evaluate`
- `dvc.lock` pins all input/output content hashes — every run is fully reproducible
- `dvc repro` reruns only changed stages (incremental execution)
- `FINETUNE_MODEL_PATH` env var switches `train.py` between full training (Run 1) and 1-epoch fine-tuning (Run 2)

### Layer 3 — MLflow (Experiment Tracking + Model Registry)
- Tracks all training runs under the `SpendSense` experiment
- Logs: 10 hyperparameters, per-epoch train/val loss and F1, final test metrics, per-class F1 for all 10 categories, confusion matrix heatmap PNG
- Model registry auto-promotes each new model version to `Staging` via `MlflowClient`
- Tracking server runs in Docker on port 5000; `mlruns/` bind-mounted for persistence

### Layer 4 — docker-compose (Runtime Orchestration)
Eight services: `mlflow`, `backend`, `frontend`, `airflow`, `prometheus`, `grafana`, `alertmanager`, `pushgateway`

### Layer 4A — FastAPI Backend (Model Serving)
- Loads model from disk on startup via `lifespan`; applies dynamic INT8 quantization on CPU (~4× memory reduction)
- 9 REST endpoints: `POST /predict`, `POST /predict/batch`, `GET /health`, `GET /ready`, `GET /metrics`, `POST /feedback`, `GET /drift`, `GET /models`, `POST /models/switch`
- `/feedback` appends ground-truth corrections to `feedback/feedback.jsonl`; `/drift` detects distribution shift vs training baseline
- All request/response schemas validated by Pydantic
- Prometheus metrics exposed at `/metrics` (pull-based scraping)

### Layer 4B — Streamlit Frontend
- **Home** (`Home.py`): single prediction, 6 example buttons, confidence bar chart, post-prediction feedback form
- **Batch Predict** (`pages/1_Batch_Predict.py`): CSV upload, paste text, HDFC bank statement XLS (with narration preprocessing to strip UPI/NEFT/RTGS prefixes)
- **Pipeline Status** (`pages/2_Pipeline_Status.py`): service health grid, live Prometheus metrics, DVC DAG diagram, Airflow DAG run history with task-level breakdown
- Communicates with backend exclusively via configurable `BACKEND_URL` env var — strict loose coupling

### Layer 4C — Prometheus + Grafana + Alertmanager + Pushgateway (Monitoring)
- FastAPI exposes `/metrics` in Prometheus text format; Prometheus scrapes every 10s
- Pushgateway receives batch-job metrics from: training, evaluation, Airflow DAG, Streamlit UI
- All 5 system components instrumented
- **Grafana** (port 3001): 8-panel dashboard auto-provisioned from JSON — Request Rate (req/s), Model Loaded, Predictions by Category, Total Requests, Latency Percentiles (P50/P95/P99), Airflow Drift Flag, Alerts Fired by Name, Recent Email Alerts
- **Alertmanager** (port 9093): 11 alert rules including `HighErrorRate > 5%` and `DataDriftDetected` (matching rubric §E); email routing via Gmail SMTP. Alert state cleanup: `pipeline_complete` task in Airflow waits 75 s after a drift-positive run (Prometheus scrape ≤15 s + rule eval ≤15 s + Alertmanager `group_wait` 30 s) before resetting the drift gauge to 0, ensuring exactly one email per drift event without re-notifications. CI skips this wait via the `GITHUB_ACTIONS=true` env flag

## Design Principles

| Principle | Implementation |
|---|---|
| Loose coupling | Frontend ↔ Backend: only via REST API calls to configurable `BACKEND_URL` |
| Reproducibility | Every experiment tied to a Git commit hash + MLflow run ID + `dvc.lock` |
| Automation | GitHub Actions triggers all stages automatically on push to main |
| Environment parity | Docker + docker-compose ensures identical dev/prod environments |
| No cloud | All services run locally; self-hosted GitHub Actions runner on local GPU |

## Technology Stack

| Concern | Tool |
|---|---|
| CI/CD Orchestrator | GitHub Actions (self-hosted runner) |
| Data Engineering | Apache Airflow 2.9 |
| ML Pipeline | DVC 3.50 |
| Experiment Tracking | MLflow 2.13 |
| Model | BiLSTM (PyTorch 2.1) — 2-layer, 256 hidden dim, bidirectional |
| Model Serving | FastAPI + Uvicorn |
| Frontend | Streamlit 1.35 |
| Containerisation | Docker + docker-compose (8 services) |
| Monitoring | Prometheus 2.52 + Grafana 10.4 + Alertmanager + Pushgateway |
| Version Control | Git + DVC |
