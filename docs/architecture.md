# Architecture Document — SpendSense

## System Overview

SpendSense is a neural-network-based personal expense classifier that automatically categorises bank transaction descriptions into one of 10 expense categories. The system follows a full MLOps architecture with clearly separated layers.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│              GitHub Actions  (CI/CD Orchestration Layer)             │
│  on: push / PR / schedule                                            │
│  jobs: lint → test → dvc repro → validate metrics → docker build    │
│         └── triggers Airflow DAG via REST API when needed            │
└───────────────┬──────────────────────────┬───────────────────────────┘
                │                          │
                ▼                          ▼
┌──────────────────────────┐   ┌───────────────────────────────────────┐
│  Airflow (Data Layer)    │   │  DVC Pipeline (ML Reproducibility)    │
│  DAG: ingestion_pipeline │   │  generate → ingest → preprocess       │
│  - schema validation     │   │         → train → evaluate            │
│  - null checks           │   │  params.yaml drives all stages        │
│  - drift detection       │   │  Git + DVC track data & model         │
│  - raw data → ingested/  │   └──────────────┬────────────────────────┘
└──────────────────────────┘                  │
                                              ▼
                               ┌──────────────────────────┐
                               │  MLflow Tracking Server  │
                               │  - metrics, params, artefacts
                               │  - Model Registry        │
                               │    (Staging → Production)│
                               └──────────────┬───────────┘
                                              │
                ┌─────────────────────────────▼─────────────────────────┐
                │             docker-compose (Runtime Layer)            │
                │  ┌─────────────────┐  ┌────────────────────────────┐ │
                │  │ FastAPI Backend │  │  Streamlit Frontend        │ │
                │  │ /predict        │←─│  Single & Batch Prediction │ │
                │  │ /health /ready  │  │  Pipeline Status Page      │ │
                │  │ /metrics        │  └────────────────────────────┘ │
                │  └────────┬────────┘                                  │
                │           │                                           │
                │  ┌────────▼────────────────────┐                     │
                │  │ Prometheus + Grafana         │                     │
                │  │ NRT dashboards, alerting     │                     │
                │  │ >5% error rate alert         │                     │
                │  └─────────────────────────────┘                     │
                └───────────────────────────────────────────────────────┘
```

## Layer Descriptions

### Layer 1 — GitHub Actions (Outer CI/CD Orchestrator)
- Sits above all other tools as the top-level control plane
- Triggers on `git push` to `main` or `develop`, pull requests, and on schedule
- Orchestrates: lint → test → DVC repro → metric validation → Docker build → smoke tests
- Uses a **self-hosted runner** (no cloud, per guidelines)

### Layer 2A — Apache Airflow (Data Orchestration)
- Manages the scheduled data ingestion workflow
- DAG tasks: generate data → validate schema → check nulls → detect drift → run ingest
- Runs independently on a `@daily` schedule; GitHub Actions can also trigger it
- Exposes a web UI on port 8080 for pipeline visibility

### Layer 2B — DVC (ML Pipeline Reproducibility)
- Defines the ML pipeline as a directed acyclic graph in `dvc.yaml`
- Stages: `generate` → `ingest` → `preprocess` → `train` → `evaluate`
- Tracks data and model versions via Git + DVC
- `dvc repro` reruns only changed stages (incremental execution)

### Layer 3 — MLflow (Experiment Tracking + Model Registry)
- Training logs: accuracy, macro F1, loss per epoch, all hyperparameters
- Artefacts: model checkpoint, vocab.pkl, label_encoder.pkl, params.yaml
- Model registry: model transitions from None → Staging → Production
- Tracking server runs in Docker on port 5000

### Layer 4 — docker-compose (Runtime Orchestration)
Six services: mlflow, backend, frontend, airflow, prometheus, grafana

### Layer 4A — FastAPI Backend (Model Serving)
- Loads model from disk artefacts on startup
- REST API: `POST /predict`, `POST /predict/batch`, `GET /health`, `GET /ready`, `GET /metrics`
- Prometheus instrumentation built in
- Loose coupling: frontend communicates only via REST API

### Layer 4B — Streamlit Frontend
- Three pages: Home (single predict), Batch Predict, Pipeline Status
- Calls FastAPI via configurable `BACKEND_URL` env var
- Shows confidence score distribution per prediction

### Layer 4C — Prometheus + Grafana (Monitoring)
- FastAPI exposes `/metrics` in Prometheus text format
- Prometheus scrapes every 10 seconds
- Grafana dashboard: request rate, P95 latency, error rate gauge, category distribution
- Alert threshold: error rate > 5%

## Design Principles

| Principle | Implementation |
|---|---|
| Loose coupling | Frontend ↔ Backend: only via REST API calls |
| Reproducibility | Every experiment tied to a Git commit hash + MLflow run ID |
| Automation | GitHub Actions triggers all stages automatically |
| Environment parity | Docker + docker-compose ensures identical dev/prod environments |
| No cloud | All services run locally; self-hosted GitHub Actions runner |

## Technology Stack

| Concern | Tool |
|---|---|
| CI/CD Orchestrator | GitHub Actions (self-hosted runner) |
| Data Engineering | Apache Airflow 2.9 |
| ML Pipeline | DVC 3.50 |
| Experiment Tracking | MLflow 2.13 |
| Model | BiLSTM (PyTorch 2.1) |
| Model Serving | FastAPI + Uvicorn |
| Frontend | Streamlit 1.35 |
| Containerisation | Docker + docker-compose |
| Monitoring | Prometheus 2.52 + Grafana 10.4 |
| Version Control | Git + DVC |
