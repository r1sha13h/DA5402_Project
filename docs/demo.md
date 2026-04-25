# SpendSense — Project Demo Guide

**Project:** DA5402 MLOps — SpendSense: Personal Expense Category Classifier  
**Stack:** BiLSTM · FastAPI · Streamlit · DVC · MLflow · Airflow · Prometheus · Grafana · GitHub Actions · Docker

---

## What SpendSense Does

Bank transaction descriptions are raw and unstructured: `NEFT CR 00023 RISHABH`, `POS ZOMATO 9148`, `UPI/PHONEPE/AMAZON`. SpendSense classifies each description into one of ten expense categories:

> Food & Dining · Transportation · Shopping & Retail · Healthcare & Medical · Entertainment & Recreation · Utilities & Services · Financial Services · Government & Legal · Income · Charity & Donations

The core model is a 2-layer Bidirectional LSTM trained on 4.5 million real bank transactions from the HuggingFace `nickmuchi/financial-classification` dataset. It achieves **98.72% macro F1** on the held-out test set.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  OUTER LAYER — CI/CD Orchestration                                   │
│  GitHub Actions (3-job pipeline on self-hosted GPU runner)           │
│  Job 1: Lint+Tests → Job 2: DVC+Infra+Airflow → Job 3: App Smoke    │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ produces model artifacts
┌────────────────────────────────▼─────────────────────────────────────┐
│  DATA LAYER — Ingestion & Drift Detection                             │
│  Apache Airflow (port 8080)                                           │
│  9-task DAG: verify → schema → nulls → drift → route →              │
│             combine_data → ingest → trigger_dvc → complete           │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ clean, validated data
┌────────────────────────────────▼─────────────────────────────────────┐
│  ML PIPELINE LAYER — Reproducible Training                            │
│  DVC (4-stage DAG in dvc.yaml)                                        │
│  ingest → preprocess → train → evaluate                               │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ trained model + artefacts
┌────────────────────────────────▼─────────────────────────────────────┐
│  EXPERIMENT TRACKING — MLflow (port 5000)                             │
│  Logs: 10 params, per-epoch metrics, per-class F1, confusion matrix  │
│  Model registry: auto-promotes to Staging after each training run    │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ model loaded via run_id
┌────────────────────────────────▼─────────────────────────────────────┐
│  SERVING LAYER — FastAPI backend (port 8000)                          │
│  POST /predict · POST /predict/batch · GET /models                   │
│  POST /models/switch · POST /feedback · GET /drift · GET /metrics    │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ REST API calls (BACKEND_URL)
┌────────────────────────────────▼─────────────────────────────────────┐
│  UI LAYER — Streamlit frontend (port 8501)                            │
│  Home: single predict + feedback · Batch Predict · Pipeline Status   │
└──────────────────────────────────────────────────────────────────────┘
                    │ metrics (scrape + push)
┌───────────────────▼──────────────────────────────────────────────────┐
│  OBSERVABILITY LAYER                                                  │
│  Prometheus (9090) · Grafana (3001) · Pushgateway (9091)             │
│  Alertmanager (9093) — 10 alert rules including HighErrorRate > 5%   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Setup

### Prerequisites

- Docker and Docker Compose installed
- 4 GB free disk space (model artefacts + data)
- Ports 5000, 8000, 8080, 8501, 9090, 9091, 9093, 3001 free

### Step 1 — Clone and prepare data

```bash
git clone https://github.com/r1sha13h/DA5402_Project.git
cd DA5402_Project
```

The raw dataset is not committed to Git (164 MB). Either:

**Option A** — Pull DVC-tracked artefacts (recommended if DVC remote is configured):
```bash
dvc pull
```

**Option B** — Run the full pipeline from scratch (requires the HuggingFace dataset):
```bash
# Download the dataset and place it at data/raw/transactions.csv
# Then run the DVC pipeline:
dvc repro
```

**Option C** — Copy from a machine that already has the data:
```bash
cp /path/to/transactions.csv data/raw/transactions.csv
dvc repro
```

### Step 2 — Configure environment

```bash
cp .env.example .env   # if present, or create manually
# Edit .env to set ALERTMANAGER_SMTP_PASSWORD if you want email alerts
# Leave it empty to disable email alerting (Alertmanager will still start)
```

### Step 3 — Start all services

```bash
docker compose up -d
```

This starts 8 services:

| Service | Port | URL |
|---|---|---|
| MLflow Tracking Server | 5000 | http://localhost:5000 |
| FastAPI Backend | 8000 | http://localhost:8000/docs |
| Streamlit Frontend | 8501 | http://localhost:8501 |
| Apache Airflow | 8080 | http://localhost:8080 (admin/admin) |
| Prometheus | 9090 | http://localhost:9090 |
| Grafana | 3001 | http://localhost:3001 (admin/admin) |
| Alertmanager | 9093 | http://localhost:9093 |
| Prometheus Pushgateway | 9091 | http://localhost:9091 |

### Step 4 — Verify everything is healthy

```bash
# All containers should show "healthy" or "running"
docker compose ps

# Model should be loaded
curl -s http://localhost:8000/ready | python3 -m json.tool

# Quick test prediction
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"description": "Zomato food delivery"}' \
  | python3 -m json.tool
```

---

## End-to-End Data Flow

### 1. Data Ingestion (Airflow)

Airflow runs the `spendsense_ingestion_pipeline` DAG on a daily schedule or on-demand trigger. The 9-task DAG:

1. **verify_raw_data** — checks that `transactions.csv` exists
2. **validate_schema** — asserts `description` and `category` columns are present
3. **check_nulls** — counts and logs null values in key columns
4. **check_drift** — loads `data/ingested/baseline_stats.json` (saved during the last ingest run) and computes per-category distribution shift vs. the current `transactions_drift.csv`. Flags any category whose share shifted > 10 percentage points
5. **route_on_drift** — `BranchPythonOperator`: routes to `combine_data` if drift detected, else to `pipeline_complete`
6. **combine_data** *(drift path only)* — merges 90% baseline + 10% drift file + `feedback/feedback.jsonl` corrections into a combined `transactions.csv`
7. **run_ingest** *(drift path only)* — runs `python -m src.data.ingest` to validate, deduplicate, and save the combined dataset to `data/ingested/`
8. **trigger_dvc** *(drift path only)* — dispatches a GitHub Actions `workflow_dispatch` event to trigger a full retraining run (skipped in CI context where `GITHUB_ACTIONS=true`)
9. **pipeline_complete** — terminal task; pushes `pipeline_complete=1.0` to Prometheus Pushgateway

All tasks push metrics to Pushgateway: rows ingested, drift flag, DVC trigger status.

### 2. ML Pipeline (DVC)

DVC defines a 4-stage reproducible pipeline in `dvc.yaml`:

```
ingest → preprocess → train → evaluate
```

**ingest** (`src/data/ingest.py`):  
Reads `data/raw/transactions.csv`, deduplicates on `(description, category)`, drops nulls, saves to `data/ingested/transactions.csv`. Also writes `baseline_stats.json` with row count and category distribution for the Airflow drift detector.

**preprocess** (`src/data/preprocess.py`):  
Tokenises descriptions (whitespace + lowercase), builds vocabulary (top-10,000 tokens, min frequency 2), pads/truncates to 50 tokens, stratified train/val/test split (70/15/15). Saves numpy arrays `X_train.npy`, `y_train.npy`, etc. Saves `vocab.pkl`, `label_encoder.pkl`, and `feature_baseline.json` (label distribution baseline for `/drift` endpoint).

**train** (`src/models/train.py`):  
Trains a `BiLSTMClassifier` (2-layer BiLSTM, 128-dim embeddings, 256 hidden dim, 0.75 dropout, batch size 512, learning rate 0.001). Supports fine-tuning: if `FINETUNE_MODEL_PATH` env var points to an existing checkpoint, loads it and trains for 1 epoch (Run 2). Otherwise trains from scratch for `params.yaml → train.epochs`. Logs to MLflow: 10 hyperparameters, per-epoch train/val loss and F1. Registers the model and auto-promotes to `Staging` via `MlflowClient`. Pushes `spendsense_training_val_f1` and `spendsense_training_duration_seconds` to Pushgateway.

**evaluate** (`src/models/evaluate.py`):  
Loads `models/latest_model.pt`, runs inference on the test set in batches, computes accuracy, macro F1, weighted F1, per-class F1, and confusion matrix. Logs all metrics and a confusion matrix heatmap PNG to MLflow. Writes `metrics/eval_metrics.json`. Exits with code 1 if `test_f1_macro < 0.70` — the DVC stage fails and CI fails. Pushes `spendsense_test_f1_macro` and `spendsense_test_accuracy` to Pushgateway.

### 3. Experiment Tracking (MLflow)

Every training run creates an MLflow run under the `SpendSense` experiment. Two run types exist:

- **`bilstm_training`** — full training from scratch (Run 1 in CI, or local runs)
- **`bilstm_finetune`** — fine-tuning from a prior checkpoint (Run 2 in CI)

Tracked artefacts: model checkpoint, `vocab.pkl`, `label_encoder.pkl`, `params.yaml`, confusion matrix PNG. The model registry tracks versions with stage transitions (`None → Staging`).

To inspect runs: open http://localhost:5000 → SpendSense experiment.

### 4. Model Serving (FastAPI)

The backend (`backend/app/predictor.py`) loads the model from disk at startup. It applies `torch.quantization.quantize_dynamic()` (INT8 on LSTM + Linear layers) when running on CPU, reducing the in-memory footprint ~4×.

Key endpoints:

```
POST /predict          — single description → category + confidence + all_scores
POST /predict/batch    — list of descriptions → list of results
GET  /models           — list MLflow runs with F1 and timestamp
POST /models/switch    — load a specific MLflow run's model (hot-swap, no restart)
POST /feedback         — log a ground-truth correction to feedback/feedback.jsonl
GET  /drift            — compute label distribution shift from feedback vs. baseline
GET  /metrics          — Prometheus metrics in exposition format
GET  /health           — liveness probe
GET  /ready            — readiness probe (model-loaded check)
```

All request and response bodies are validated by Pydantic schemas.

### 5. Frontend (Streamlit)

Three pages:

**Home** (`frontend/Home.py`): Single prediction with 6 example buttons. Displays predicted category, confidence with plain-English explanation, and full score distribution. After a prediction, shows a feedback form where users can correct wrong labels (calls `POST /feedback`). Sidebar shows model readiness, current MLflow run ID, and a model-switching dropdown.

**Batch Predict** (`frontend/pages/1_Batch_Predict.py`): Three tabs — CSV upload, paste descriptions, HDFC bank statement XLS. Classifies all descriptions in one call to `POST /predict/batch`. Displays a results table, category distribution bar chart, and CSV download button.

**Pipeline Status** (`frontend/pages/2_Pipeline_Status.py`): Shows live health for all 7 external services. Displays live Prometheus metric counters. Renders the DVC pipeline DAG (via `dvc dag` subprocess with Graphviz). Provides direct links to MLflow, Airflow, Grafana, Prometheus, Pushgateway, and Alertmanager UIs.

### 6. Monitoring (Prometheus + Grafana)

**What is instrumented:**

| Component | Metrics | Push method |
|---|---|---|
| FastAPI backend | requests_total, latency_seconds, error_rate, model_loaded, predictions_by_category, batch_size | `/metrics` endpoint (pull) |
| Training pipeline | training_val_f1, training_duration_seconds | Pushgateway |
| Evaluation pipeline | test_f1_macro, test_accuracy | Pushgateway |
| Airflow DAG | pipeline_drift_detected, pipeline_rows_ingested, pipeline_ingest_success, pipeline_dvc_triggered, pipeline_complete | Pushgateway |
| Streamlit frontend | ui_predictions_total, ui_errors_total, ui_batch_items_total | Pushgateway |

**Alert rules** (10 rules across 4 groups):
- `HighErrorRate` — error rate > 5% for 2 min (matches rubric exactly)
- `ModelNotLoaded` — model unavailable > 1 min (critical)
- `HighPredictionLatency` — P95 > 500ms on /predict for 5 min
- `LowTestF1` — test F1 drops below 0.70 (immediate)
- `LowValF1` — validation F1 < 0.65 during training
- `TrainingDurationHigh` — training takes > 2 hours
- `DataDriftDetected` — Airflow flags drift (immediate)
- `IngestFailed` — ingest task fails (critical)
- `FeedbackLoopDead` — no feedback in 24h
- `TailLatencySpike` — P99 > 1s for 5 min
- `LowRequestRate` — near-zero traffic for 10 min
- `FrequentModelSwitch` — > 3 hot-swaps in 1 hour

**Grafana dashboard** (17 panels): Request Rate, P95 Latency, Model Loaded, Predictions by Category, Total Requests, Batch Size Distribution, Training Duration, Latency Percentiles (P50/P95/P99), Feedback Entries, Max Drift Score, Airflow Drift Flag, Rows Ingested, Model Hot-Swaps, Alertmanager Alerts Firing.

---

## Key MLOps Principles Demonstrated

| Principle | Implementation |
|---|---|
| **Reproducibility** | Every experiment is reproducible via a specific Git commit hash + MLflow run ID. `dvc.lock` pins all input hashes |
| **Automation** | Full ML lifecycle automated: ingestion (Airflow) → pipeline (DVC) → tracking (MLflow) → serving (FastAPI) → monitoring (Prometheus) → retraining trigger (GitHub Actions) |
| **Continuous Integration** | 3-job GitHub Actions pipeline on self-hosted runner with F1 quality gate |
| **Version Control** | Git for code; DVC for data, processed arrays, and model weights; MLflow for experiments |
| **Environment Parity** | All 8 services run in Docker containers. `MLproject` + `python_env.yaml` define the training environment |
| **Monitoring & Logging** | All 5 components instrumented; 10 alert rules; structured logging with `logging` module throughout |
| **Feedback Loop** | `POST /feedback` collects ground-truth labels; `GET /drift` detects distribution shift; Airflow DAG triggers retraining when drift exceeds 10 pp |
| **Model Registry** | MLflow registry with automated Staging promotion; `/models/switch` allows zero-downtime model hot-swap |

---

## Feedback Loop & Drift Detection

The feedback loop closes the production monitoring cycle:

```
User corrects a prediction
    ↓
POST /feedback (description, predicted, actual)
    ↓
feedback/feedback.jsonl (appended)
    ↓
GET /drift
    reads feedback.jsonl → computes actual_category distribution
    compares vs feature_baseline.json → per-category shift
    flags any category shifted > 10 pp
    ↓
Airflow check_drift task (daily run)
    reads transactions_drift.csv → compares vs baseline_stats.json
    if drift detected → combine_data → run_ingest → trigger_dvc
    ↓
GitHub Actions workflow_dispatch → DVC repro (retraining)
```

---

## Rollback Mechanisms

Three independent rollback paths:

1. **Git + DVC:** `git checkout <commit> && dvc checkout` restores any prior pipeline state including model weights
2. **MLflow hot-swap:** `POST /models/switch` loads any prior MLflow run's model at runtime without container restart
3. **Full environment:** `docker compose down && git checkout <tag> && docker compose up` resets the entire stack

---

## Pre-Demo Checklist

Run 10 minutes before demonstration:

```bash
# 1. All services up
docker compose ps

# 2. Model loaded
curl -s http://localhost:8000/ready | python3 -c "import json,sys; d=json.load(sys.stdin); print('READY' if d['ready'] else 'NOT READY')"

# 3. MLflow experiments exist
curl -s "http://localhost:5000/api/2.0/mlflow/experiments/list" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('experiments',[])), 'experiments')"

# 4. Quick prediction warmup
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"description": "Zomato food delivery"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['predicted_category'], round(d['confidence'],3))"

# 5. Generate Grafana traffic
for desc in "Zomato delivery" "Uber ride" "Netflix" "Apollo pharmacy" \
            "BESCOM bill" "Amazon order" "SIP investment" "Salary credit"; do
  curl -s -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d "{\"description\": \"$desc\"}" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(d['description'],'→',d['predicted_category'])"
done
```
