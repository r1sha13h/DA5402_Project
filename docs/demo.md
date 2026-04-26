# SpendSense — End-to-End Demo Guide

**Project:** DA5402 MLOps — SpendSense: Personal Expense Category Classifier
**Stack:** BiLSTM · FastAPI · Streamlit · DVC · MLflow · Airflow · Prometheus · Grafana · GitHub Actions · Docker

---

## What SpendSense Does

Bank transaction descriptions are raw and unstructured: `NEFT CR 00023 RISHABH`, `POS ZOMATO 9148`, `UPI/PHONEPE/AMAZON`. SpendSense classifies each description into one of ten expense categories:

> Food & Dining · Transportation · Shopping & Retail · Healthcare & Medical · Entertainment & Recreation · Utilities & Services · Financial Services · Government & Legal · Income · Charity & Donations

The core model is a 2-layer Bidirectional LSTM trained on 4.5 million real bank transactions from HuggingFace `nickmuchi/financial-classification`. It achieves **98.72% macro F1** on the held-out test set.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  OUTER LAYER — CI/CD Orchestration                                   │
│  GitHub Actions (3-job BAT pipeline, self-hosted GPU runner, ~13m)  │
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
                                 │ model loaded via MODEL_PATH volume mount
┌────────────────────────────────▼─────────────────────────────────────┐
│  SERVING LAYER — FastAPI backend (port 8000)                          │
│  POST /predict · POST /predict/batch · GET /models                   │
│  POST /models/switch · POST /feedback · GET /drift · GET /metrics    │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ REST API calls (BACKEND_URL)
┌────────────────────────────────▼─────────────────────────────────────┐
│  UI LAYER — Streamlit frontend (port 8501)                            │
│  Home: single predict + feedback                                      │
│  Batch Predict: CSV / paste / HDFC XLS                                │
│  Pipeline Status: health grid + DAG + run history                    │
└──────────────────────────────────────────────────────────────────────┘
                    │ metrics (scrape + push)
┌───────────────────▼──────────────────────────────────────────────────┐
│  OBSERVABILITY LAYER                                                  │
│  Prometheus (9090) · Grafana (3001) · Pushgateway (9091)             │
│  Alertmanager (9093) — 11 alert rules including HighErrorRate > 5%  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Setup

### Prerequisites

- Docker and Docker Compose installed
- 4 GB free disk space
- Ports 5000, 8000, 8080, 8501, 9090, 9091, 9093, 3001 free
- Trained model at `models/latest_model.pt` (produced by CI or `dvc repro`)

### Step 1 — Clone

```bash
git clone https://github.com/r1sha13h/DA5402_Project.git
cd DA5402_Project
```

The raw dataset is not committed to Git (164 MB). To get the model and processed data, either:

**Option A** — Pull DVC-tracked artifacts (if DVC remote configured):
```bash
dvc pull
```

**Option B** — Run the full pipeline from scratch:
```bash
# Place data at data/raw/transactions.csv, then:
source venv/bin/activate
dvc repro
```

**Option C** — Let CI produce the artifacts (on push to main, CI produces `models/latest_model.pt` and all processed files).

### Step 2 — Configure environment (optional)

```bash
# Only needed for email alerts — leave empty to disable
export ALERTMANAGER_SMTP_PASSWORD=your_gmail_app_password
```

### Step 3 — Start all services

```bash
docker compose up -d
```

All 8 services start:

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

### Step 4 — Verify

```bash
docker compose ps
curl -s http://localhost:8000/ready | python3 -m json.tool
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"description": "Zomato food delivery"}' \
  | python3 -m json.tool
```

---

## End-to-End Data Flow

### 1. Data Ingestion (Airflow)

Airflow runs the `spendsense_ingestion_pipeline` DAG on `@daily` schedule or on-demand trigger.

**9-task chain:**
1. **verify_raw_data** — checks that data files exist at expected paths
2. **validate_schema** — asserts `description` and `category` columns are present
3. **check_nulls** — counts and logs null values
4. **check_drift** — loads `baseline_stats.json`, computes per-category distribution shift vs `transactions_drift.csv`; flags any shift > 10 pp
5. **route_on_drift** — `BranchPythonOperator`: routes to `combine_data` if drift detected, else to `pipeline_complete`
6. **combine_data** *(drift path only)* — merges 90% baseline + 10% drift file + `feedback/feedback.jsonl` corrections
7. **run_ingest** *(drift path only)* — validates and deduplicates combined dataset; saves to `data/ingested/`; skipped in CI (DVC Run 2 handles this)
8. **trigger_dvc** *(drift path only)* — dispatches GitHub Actions `workflow_dispatch` to retrain; skipped in CI
9. **pipeline_complete** — terminal task with `trigger_rule="none_failed_min_one_success"`; pushes `pipeline_complete=1.0` to Pushgateway

### 2. ML Pipeline (DVC)

4-stage reproducible pipeline in `dvc.yaml`:

```
ingest → preprocess → train → evaluate
```

- **ingest:** Reads `transactions.csv`, deduplicates, validates, writes `data/ingested/transactions.csv` + `baseline_stats.json`
- **preprocess:** Tokenises, builds vocab (10K tokens, min_freq=2), pads to 50, stratified 70/15/15 split, writes numpy arrays + `vocab.pkl` + `label_encoder.pkl` + `feature_baseline.json`
- **train:** Trains BiLSTMClassifier (or fine-tunes from `FINETUNE_MODEL_PATH`). Logs to MLflow as `bilstm_training` (Run 1) or `bilstm_finetune` (Run 2). Auto-promotes to `Staging`. Pushes training metrics to Pushgateway.
- **evaluate:** Test-set eval, confusion matrix heatmap PNG logged to MLflow, writes `metrics/eval_metrics.json`. Exits non-zero if F1 < 0.70.

### 3. Experiment Tracking (MLflow)

Two run types under `SpendSense` experiment:
- **`bilstm_training`** — full training from scratch (Run 1)
- **`bilstm_finetune`** — 1-epoch fine-tuning from prior checkpoint (Run 2)

Open http://localhost:5000 → SpendSense experiment to inspect runs.

### 4. Model Serving (FastAPI)

Backend loads model from `models/latest_model.pt` at startup. Applies INT8 quantization on CPU (~4× memory reduction).

Key endpoints:
```
POST /predict          → category + confidence + all_scores (10 values)
POST /predict/batch    → list of results
GET  /models           → list MLflow runs with F1 and timestamp
POST /models/switch    → load a specific run's model (hot-swap, no restart)
POST /feedback         → log ground-truth correction to feedback.jsonl
GET  /drift            → distribution shift from feedback vs. baseline
GET  /metrics          → Prometheus metrics exposition format
GET  /health           → liveness probe
GET  /ready            → readiness probe (model-loaded check)
```

### 5. Frontend (Streamlit)

**Home** (`http://localhost:8501`):
- Single prediction with 6 example buttons
- Confidence bar chart with plain-English explanation
- Post-prediction feedback form (`POST /feedback`)

**Batch Predict** (`http://localhost:8501/Batch_Predict`):
- Three tabs: CSV upload, paste text, HDFC bank statement XLS
- HDFC XLS: auto-detects header row, filters debit transactions, strips UPI/NEFT/POS prefixes
- Altair donut chart + CSV download

**Pipeline Status** (`http://localhost:8501/Pipeline_Status`):
- Live health grid for all 7 services
- Live Prometheus metric counters
- DVC DAG diagram (Graphviz)
- Airflow DAG run history with task-level breakdown
- Direct links to all tool UIs

### 6. Monitoring (Prometheus + Grafana)

**Instrumented components (5):**

| Component | Metrics | Method |
|---|---|---|
| FastAPI backend | requests_total, latency_seconds, error_rate, model_loaded, predictions_by_category, batch_size, feedback_total, drift_score, model_switches | `/metrics` pull |
| Training pipeline | training_val_f1, training_duration_seconds | Pushgateway |
| Evaluation pipeline | test_f1_macro, test_accuracy | Pushgateway |
| Airflow DAG | pipeline_drift_detected, pipeline_rows_ingested, pipeline_ingest_success, pipeline_dvc_triggered, pipeline_complete | Pushgateway |
| Streamlit frontend | ui_predictions_total, ui_errors_total, ui_batch_items_total | Pushgateway |

**Alert rules (11):**
- `HighErrorRate` — error rate > 5% for 2 min *(matches rubric §E)*
- `ModelNotLoaded` — model unavailable > 1 min *(critical)*
- `HighPredictionLatency` — P95 > 500ms for 5 min
- `LowTestF1` — test F1 < 0.70 *(immediate)*
- `LowValF1` — val F1 < 0.65 during training
- `TrainingDurationHigh` — training > 2 hours
- `DataDriftDetected` — Airflow drift flag fires *(matches rubric §E)*
- `IngestFailed` — ingest task fails *(critical)*
- `FeedbackLoopDead` — no new feedback in 48h
- `TailLatencySpike` — P99 > 1s for 5 min
- `FrequentModelSwitch` — > 3 hot-swaps in 1 hour

**Grafana dashboard (7 panels, http://localhost:3001):**
Auto-provisioned from `monitoring/grafana/provisioning/dashboards/spendsense.json`:
- Request Rate · Error Rate · Feedback Count · Drift Score · Latency Percentiles (P50/P95/P99) · Model Info · Alert Firing History

---

## Key MLOps Principles Demonstrated

| Principle | Implementation |
|---|---|
| **Reproducibility** | Git commit + MLflow run ID + `dvc.lock` hashes tie every experiment |
| **Automation** | Full ML lifecycle: ingestion → pipeline → tracking → serving → monitoring → retraining — automated on push |
| **Continuous Integration** | 3-job GitHub Actions BAT pipeline, self-hosted GPU runner, F1 quality gate |
| **Version Control** | Git (code), DVC (data+models), MLflow (experiments+registry) |
| **Environment Parity** | 8 services Docker-containerized; `MLproject` + `python_env.yaml` for training |
| **Monitoring & Logging** | 5 components instrumented; 11 alert rules; structured logging throughout |
| **Feedback Loop** | `POST /feedback` → `feedback.jsonl` → `GET /drift` detects shift → Airflow triggers retraining |
| **Model Registry** | Auto-Staging promotion; `/models/switch` zero-downtime hot-swap |

---

## Feedback Loop & Drift Detection

```
User corrects a prediction via the feedback form
    ↓
POST /feedback (description, predicted, actual)
    ↓
feedback/feedback.jsonl (appended)
    ↓
GET /drift
    reads feedback.jsonl → computes actual_category distribution
    compares vs feature_baseline.json → per-category shift
    flags any shift > 10 pp (requires ≥ 100 samples)
    ↓
Airflow check_drift (daily)
    reads transactions_drift.csv → compares vs baseline_stats.json
    if drift detected → combine_data → run_ingest → trigger_dvc
    ↓
GitHub Actions workflow_dispatch → DVC repro (retraining)
```

---

## Rollback Mechanisms

1. **Git + DVC:** `git checkout <commit> && dvc checkout` restores any prior state including model weights
2. **MLflow hot-swap:** `POST /models/switch {"run_id": "<prior_run_id>"}` loads any prior model without container restart
3. **Full environment:** `docker compose down && git checkout <tag> && docker compose up`

---

## Pre-Demo Checklist

Run 10 minutes before demonstration:

```bash
# 1. All 8 services healthy
docker compose ps

# 2. Model loaded and ready
curl -s http://localhost:8000/ready | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('READY' if d['ready'] else 'NOT READY')"

# 3. MLflow has experiments
curl -s "http://localhost:5000/api/2.0/mlflow/experiments/list" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(len(d.get('experiments',[])), 'experiments')"

# 4. Quick prediction warmup
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"description": "Zomato food delivery"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['predicted_category'], round(d['confidence'],3))"

# 5. Generate traffic to populate Grafana panels
for desc in "Zomato delivery" "Uber ride" "Netflix" "Apollo pharmacy" \
            "BESCOM bill" "Amazon order" "SIP investment" "Salary credit" \
            "BookMyShow tickets" "LIC premium"; do
  curl -s -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d "{\"description\": \"$desc\"}" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(d['description'],'→',d['predicted_category'])"
done

# 6. Reset feedback.jsonl for clean /drift demo (optional)
# cp /dev/null feedback/feedback.jsonl
```

---

## Demo Script (Suggested Flow)

### Step 1 — Start with GitHub Actions (~2 min)
Open the latest successful CI run on GitHub Actions. Walk through the 3 jobs:
- Job 1: lint + 68 tests (40s)
- Job 2: 90-10 split → DVC Run 1 → Airflow DAG → DVC Run 2 (11 min)
- Job 3: artifact download → smoke tests (1.5 min)

Highlight: self-hosted GPU runner, F1 quality gate, two-run training pattern.

### Step 2 — Airflow DAG (~2 min)
Open http://localhost:8080. Navigate to `spendsense_ingestion_pipeline`.
- Show the 9-task DAG graph
- Show the last successful run with all tasks green
- Click into `check_drift` and show the log confirming drift was detected

### Step 3 — DVC Pipeline (~1 min)
In terminal: `dvc dag` to show the 4-stage pipeline.
Highlight: `dvc.lock` pinning hashes, reproducibility guarantee.

### Step 4 — MLflow UI (~2 min)
Open http://localhost:5000. Navigate to `SpendSense` experiment.
- Show both run types: `bilstm_training` (Run 1) and `bilstm_finetune` (Run 2)
- Click into a run: show 10 parameters, per-epoch F1 curve, confusion matrix PNG artifact
- Show model registry: `SpendSense` model in `Staging` stage

### Step 5 — Streamlit UI (~3 min)
Open http://localhost:8501.
- **Home:** Click example button → Classify → show confidence chart → submit feedback
- **Batch Predict:** Upload a CSV or paste 5–10 descriptions → show results table + donut chart
- **Pipeline Status:** Show service health grid, live metrics, DAG diagram, Airflow run history

### Step 6 — FastAPI Swagger (~1 min)
Open http://localhost:8000/docs. Show the 9 endpoints with schemas.
Run `/predict` interactively.

### Step 7 — Prometheus + Grafana (~2 min)
Open http://localhost:9090. Show `spendsense_requests_total` query.
Open http://localhost:3001. Walk through the 7 Grafana panels: request rate, latency percentiles, drift score, alert firing history.

### Step 8 — Model hot-swap (~1 min)
In terminal:
```bash
curl -s http://localhost:8000/models | python3 -m json.tool
# Note a run_id, then switch:
curl -s -X POST http://localhost:8000/models/switch \
  -H "Content-Type: application/json" \
  -d '{"run_id": "<run_id>"}' | python3 -m json.tool
```
Highlight: zero-downtime, no container restart required.
