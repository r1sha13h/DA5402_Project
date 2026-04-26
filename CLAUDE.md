# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Activate the project virtualenv (required before any Python commands)
source venv/bin/activate

# Lint
flake8 src/ backend/ tests/ --max-line-length=100 --exclude=__pycache__

# Run all tests with coverage (must meet 60% threshold)
pytest tests/ -v --cov=src --cov=backend --cov-report=term-missing --cov-fail-under=60

# Run a single test file
pytest tests/test_api.py -v

# Run a single test function
pytest tests/test_model.py::TestBiLSTMClassifier::test_forward_pass -v

# Run the full DVC ML pipeline (requires raw data at data/raw/transactions.csv)
dvc repro

# Run DVC pipeline forcing all stages to re-run
dvc repro --force

# Start all services locally
docker compose up -d

# Start only infra services (MLflow, Prometheus, Grafana, Alertmanager, Pushgateway)
docker compose up -d mlflow alertmanager pushgateway prometheus grafana

# Start only app services (backend + frontend) — requires processed data and model
docker compose up -d backend frontend

# Tear down everything
docker compose down
```

## Project Overview

**SpendSense** is a BiLSTM-based bank transaction expense classifier built as a DA5402 MLOps course project. It classifies raw transaction descriptions (e.g. `"NEFT CR RISHABH"`, `"POS ZOMATO 9148"`) into 10 expense categories. Dataset: 4.5M real transactions from HuggingFace `nickmuchi/financial-classification`. Achieved test macro F1 = **98.72%**.

### 10 Expense Categories
`Food & Dining` · `Transportation` · `Shopping & Retail` · `Healthcare & Medical` · `Entertainment & Recreation` · `Utilities & Services` · `Financial Services` · `Government & Legal` · `Income` · `Charity & Donations`

## Architecture

Five layers, outer to inner:

```
GitHub Actions CI/CD (3-job BAT pipeline, self-hosted runner)
    ↓
Airflow (spendsense_ingestion_pipeline DAG, @daily)
    ↓
DVC (4-stage pipeline: ingest → preprocess → train → evaluate)
    ↓
MLflow (experiment tracking + model registry)
    ↓
docker-compose (8 services: FastAPI · Streamlit · MLflow · Airflow · Prometheus · Grafana · Alertmanager · Pushgateway)
```

## Data & ML Pipeline (DVC — `dvc.yaml`)

Four sequential stages driven by scripts in `src/`:

1. **ingest** (`src/data/ingest.py`) — loads `data/raw/transactions.csv`, deduplicates on `(description, category)`, validates schema/nulls/categories, writes `data/ingested/transactions.csv` + `baseline_stats.json` (used by Airflow drift detector)
2. **preprocess** (`src/data/preprocess.py`) — whitespace tokenisation, lowercase, vocab (top-10K, min_freq=2), pads/truncates to 50 tokens, stratified 70/15/15 split, writes `.npy` arrays + `vocab.pkl` + `label_encoder.pkl` + `feature_baseline.json`
3. **train** (`src/models/train.py`) — trains `BiLSTMClassifier`, logs to MLflow as run type `bilstm_training` (Run 1) or `bilstm_finetune` (Run 2 when `FINETUNE_MODEL_PATH` is set), auto-promotes to `Staging` in MLflow registry, pushes metrics to Pushgateway
4. **evaluate** (`src/models/evaluate.py`) — test-set eval, logs confusion matrix heatmap PNG to MLflow, writes `metrics/eval_metrics.json`, exits non-zero if F1 < 0.70 (CI gate)

All hyperparameters in `params.yaml`. Model architecture in `src/models/model.py`: Embedding → BiLSTM (2 layers, 256 hidden, bidirectional) → Dropout → Linear → ReLU → Dropout → Linear.

## CI/CD (`.github/workflows/ci.yml`) — self-hosted GPU runner

Three jobs (total ~13 min):

- **Job 1 (test, ~40s)**: flake8 + pytest on every push to any branch
- **Job 2 (ml-pipeline, ~11 min)**: main-branch only
  1. Splits data 90/10 via `scripts/create_drift_split.py` (stratified 90% baseline + intentionally skewed 10% drift file)
  2. Starts infra services (MLflow, Prometheus, Grafana, Alertmanager, Pushgateway)
  3. **DVC Run 1** on 90% data → saves `models/run1_model.pt`
  4. Builds and starts Airflow immediately after Run 1 (before Prometheus verify step, so the healthcheck wait overlaps)
  5. Triggers `spendsense_ingestion_pipeline` DAG (drift detection → `combine_data` merges 90%+10%+feedback)
  6. **DVC Run 2** fine-tunes with `FINETUNE_MODEL_PATH=models/run1_model.pt` on merged data
- **Job 3 (app, ~1.5 min)**: main-branch only — downloads Job 2 artifacts (model, vocab, label_encoder, mlruns), smoke-tests FastAPI + Streamlit via Docker

**Artifact upload (Job 2 → Job 3):** `models/latest_model.pt`, `data/processed/vocab.pkl`, `data/processed/label_encoder.pkl`, `data/processed/feature_baseline.json`, `mlruns/mlflow.db`, `params.yaml`. `run1_model.pt` is only needed within Job 2 for fine-tuning and is not uploaded. Job 3 loads the model via `MODEL_PATH=/app/models/latest_model.pt` volume mount — it does not use MLflow artifact store.

**CI skip pattern:** `task_run_ingest` in the Airflow DAG returns immediately when `GITHUB_ACTIONS=true` (the env var is forwarded to the Airflow container via docker-compose). DVC Run 2 re-runs ingest anyway, so the Airflow ingest step would be redundant in CI.

## FastAPI Backend (`backend/app/`)

- `main.py` — FastAPI app; loads model on startup via `lifespan`. Endpoints:
  - `POST /predict` — single description → `{predicted_category, confidence, all_scores}`
  - `POST /predict/batch` — list of descriptions → list of results
  - `GET /models` — list MLflow FINISHED runs with metrics
  - `POST /models/switch` — zero-downtime model hot-swap from any MLflow run
  - `POST /feedback` — appends ground-truth correction to `feedback/feedback.jsonl`
  - `GET /drift` — compares `actual_category` distribution in `feedback.jsonl` vs `feature_baseline.json`; flags >10pp shift; requires ≥100 samples
  - `GET /metrics` — Prometheus exposition
  - `GET /health` / `GET /ready`
- `predictor.py` — `SpendSensePredictor` singleton; applies `torch.quantization.quantize_dynamic()` (INT8 on LSTM+Linear) on CPU; `load_from_mlflow(run_id)` downloads and swaps model at runtime
- `monitoring.py` — all Prometheus metrics: `FEEDBACK_TOTAL`, `DRIFT_SCORE`, `MODEL_SWITCHES`, `REQUEST_COUNT`, `REQUEST_LATENCY`, `PREDICTION_CATEGORY`, `BATCH_SIZE`, `MODEL_LOADED`
- `schemas.py` — Pydantic request/response models for all endpoints

## Streamlit Frontend (`frontend/`)

Three pages:
- **Home** (`Home.py`): single prediction, 6 example buttons that pre-fill the input, confidence bar chart, post-prediction feedback form (calls `POST /feedback`). The example buttons use `st.session_state.get("example_input")` (not `pop`) so the value survives into the form-submit rerun; `pop` happens inside `if submitted:` only.
- **Batch Predict** (`pages/1_Batch_Predict.py`): three tabs — CSV upload, paste descriptions, HDFC bank statement XLS upload (auto-detects header row, filters withdrawal transactions). Results table, Altair donut chart, CSV download button. HDFC narrations are preprocessed by `_clean_hdfc_narration()` which strips UPI/NEFT/RTGS/etc. prefixes before inference.
- **Pipeline Status** (`pages/2_Pipeline_Status.py`): health grid for all 7 services, live Prometheus metric counters, DVC DAG diagram via `dvc dag` + Graphviz, direct links to all tool UIs, Airflow DAG run history with task-level breakdown (queries Airflow REST API with Basic auth).

Frontend communicates with backend exclusively via configurable `BACKEND_URL` env var. `PROMETHEUS_URL` and `ALERTMANAGER_URL` must be set to `http://prometheus:9090` and `http://alertmanager:9093` respectively (set in `docker-compose.yml`) — `localhost` is unreachable inside the Docker network.

## Airflow DAG (`airflow/dags/ingestion_dag.py`)

DAG ID: `spendsense_ingestion_pipeline`, `@daily`. Task chain:

```
verify_raw_data → validate_schema → check_nulls → check_drift → route_on_drift (BranchPythonOperator)
    ├── drift detected  → combine_data → run_ingest → trigger_dvc → pipeline_complete
    └── no drift        ─────────────────────────────────────────→ pipeline_complete
```

- `combine_data`: merges `data/raw/transactions_90.csv` + `data/drift/transactions_drift.csv` + `feedback/feedback.jsonl` (as description/actual_category pairs) → `data/raw/transactions.csv`
- `trigger_dvc`: dispatches GitHub Actions `workflow_dispatch` to retrain; is a no-op when `GITHUB_ACTIONS=true` (CI runner drives Run 2 directly)
- `run_ingest`: no-op when `GITHUB_ACTIONS=true` (DVC Run 2 re-runs ingest anyway)
- `pipeline_complete` uses `trigger_rule="none_failed_min_one_success"` — fires regardless of which branch was taken
- All tasks push metrics to Prometheus Pushgateway

## Monitoring Stack

| Service | Host Port | Container Name |
|---|---|---|
| FastAPI backend | 8000 | spendsense_backend |
| Streamlit frontend | 8501 | spendsense_frontend |
| MLflow | 5000 | spendsense_mlflow |
| Airflow | 8080 | spendsense_airflow (admin/admin) |
| Prometheus | 9090 | spendsense_prometheus |
| Pushgateway | 9091 | spendsense_pushgateway |
| Grafana | 3001 | spendsense_grafana (admin/admin) |
| Alertmanager | 9093 | spendsense_alertmanager |

**What is instrumented (5 components):** FastAPI backend (pull via `/metrics`), training pipeline, evaluation pipeline, Airflow DAG, Streamlit frontend — all push to Pushgateway.

**Alert rules (11):** `HighErrorRate > 5%`, `DataDriftDetected`, `ModelNotLoaded`, `HighPredictionLatency`, `LowTestF1`, `LowValF1`, `TrainingDurationHigh`, `IngestFailed`, `FeedbackLoopDead` (48h `for:` — not instant-firing), `TailLatencySpike`, `FrequentModelSwitch`

**Grafana:** 7 panels auto-provisioned from JSON at startup: Request Rate, Error Rate, Feedback Count, Drift Score, Latency Percentiles (P50/P95/P99), Model Info, Alert Firing History (`ALERTS{alertstate="firing"}` by alertname). Note: Grafana internal port is 3000, host port is 3001 — Docker inter-service config uses `grafana:3000`.

## Feedback Loop & Drift Detection

```
POST /feedback (description, predicted, actual)
    → feedback/feedback.jsonl
    → GET /drift detects distribution shift vs feature_baseline.json (≥100 samples, >10pp threshold)
    → Airflow check_drift (daily) compares transactions_drift.csv vs baseline_stats.json
    → combine_data merges 90%+drift+feedback → run_ingest → trigger_dvc (retraining)
```

`feedback/feedback.jsonl` persists across CI runs (copied to/from runner's project directory).

## Rollback Mechanisms

1. **Git + DVC:** `git checkout <commit> && dvc checkout` restores any prior pipeline state
2. **MLflow hot-swap:** `POST /models/switch` loads any prior run's model without container restart
3. **Full environment:** `docker compose down && git checkout <tag> && docker compose up`

## Key Invariants

- `train.py` and `evaluate.py` are excluded from coverage in `setup.cfg` (require full DVC artifacts)
- `FINETUNE_MODEL_PATH` env var in `train.py` switches between full training (Run 1) and fine-tuning (Run 2 for 1 epoch)
- `mlruns/` is bind-mounted into MLflow container and persisted back to the project directory after each CI run; only `mlruns/mlflow.db` is transferred as a CI artifact (full `mlruns/` with binary model duplicates was too slow)
- `feedback/feedback.jsonl` must be reset before demo for a clean `/drift` result (contains CI test entries)
- **MLproject has known issues:** stale `generate` entry point and hyperparameter mismatch vs `params.yaml` — use `dvc repro` not `mlflow run .` to reproduce training
- `data/drift/transactions_drift.csv` is the 10% intentionally skewed split polled by Airflow; `data/raw/transactions_90.csv` is the 90% baseline; both are created by `scripts/create_drift_split.py`
- Home page has no model-selection sidebar (removed) — use `POST /models/switch` API directly or the Pipeline Status page
