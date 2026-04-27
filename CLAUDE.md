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

# Run a single test file / function
pytest tests/test_api.py -v
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
GitHub Actions CI/CD (3-job pipeline, self-hosted GPU runner)
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

Four sequential stages:

1. **ingest** (`src/data/ingest.py`) — loads `data/raw/transactions.csv`, deduplicates on `(description, category)`, validates schema/nulls/categories, writes `data/ingested/transactions.csv` + `baseline_stats.json` (used by Airflow drift detector)
2. **preprocess** (`src/data/preprocess.py`) — whitespace tokenisation, lowercase, vocab (top-10K, min_freq=2), pads/truncates to 50 tokens, stratified 70/15/15 split, writes `.npy` arrays + `vocab.pkl` + `label_encoder.pkl` + `feature_baseline.json`
3. **train** (`src/models/train.py`) — trains `BiLSTMClassifier` for `params.yaml:train.epochs` epochs (currently 1). When `FINETUNE_MODEL_PATH` is set and the file exists, loads those weights and runs for exactly 1 epoch (fine-tune); MLflow run name is `bilstm_finetune` vs `bilstm_training`. Auto-promotes to `Staging` in MLflow registry. Pushes metrics to Pushgateway.
4. **evaluate** (`src/models/evaluate.py`) — test-set eval, logs confusion matrix heatmap PNG to MLflow, writes `metrics/eval_metrics.json`, exits non-zero if F1 < 0.70 (CI gate). Pushes `spendsense_test_f1_macro` and `spendsense_test_accuracy` to Pushgateway.

All hyperparameters in `params.yaml`. DVC remote is a local path: `/home/rishabh/.dvc_remote_da5402`.

**Model architecture** (`src/models/model.py`): `Embedding(vocab_size, 128)` → `BiLSTM(2 layers, hidden=256, bidirectional)` → `Dropout` → `Linear(512→256)` → `ReLU` → `Dropout` → `Linear(256→10)`. Forward pass concatenates the last-layer forward and backward hidden states.

## CI/CD (`.github/workflows/ci.yml`) — self-hosted GPU runner

Three jobs (total ~18 min observed):

- **Job 1 (test, ~30s)**: flake8 + pytest on every push to any branch
- **Job 2 (ml-pipeline, ~16 min)**: triggers on push to `main` OR `workflow_dispatch` with `run_full_pipeline=true`
  1. Splits data 90/10 via `scripts/create_drift_split.py` (stratified 90% baseline + intentionally skewed 10% drift file)
  2. Starts infra services (MLflow, Prometheus, Grafana, Alertmanager, Pushgateway)
  3. **DVC Run 1** on 90% data → saves `models/run1_model.pt`
  4. Builds and starts Airflow immediately after Run 1
  5. Triggers `spendsense_ingestion_pipeline` DAG via Basic Auth POST to `/api/v1/dags/.../dagRuns`; polls every 5s, exits early on `state=success` (typically ~50s)
  6. After DAG success, `data/raw/transactions.csv` contains the 90%+10%+feedback merge written by `combine_data` (~1.28M rows)
  7. **DVC Run 2** with `FINETUNE_MODEL_PATH=models/run1_model.pt` (fine-tune, 1 epoch on the merged corpus)
  8. Stages artifacts to `$HOME/ss-ci-$GITHUB_RUN_ID/` for Job 3
- **Job 3 (app, ~45s)**: main-branch only (no `workflow_dispatch` escape hatch) — restores artifacts from local stage, smoke-tests FastAPI + Streamlit via Docker, cleans up stage dir

**Artifact passing (Job 2 → Job 3):** Copied to `$HOME/ss-ci-$GITHUB_RUN_ID/` (a path that persists across jobs on a self-hosted runner). Never goes through GitHub's artifact API. Files: `models/latest_model.pt`, `data/processed/vocab.pkl`, `data/processed/label_encoder.pkl`, `data/processed/feature_baseline.json`, `mlruns/mlflow.db`, `params.yaml`.

**CI skip pattern:** `task_run_ingest` in the Airflow DAG returns immediately when `GITHUB_ACTIONS=true` (DVC Run 2 re-runs ingest anyway). `task_trigger_dvc` skips with reason `ci_context` (CI runner drives DVC Run 2 directly).

## Airflow REST API Auth (fix already applied)

Airflow 2.9 defaults to session-only auth, which silently rejected the CI's `Authorization: Basic admin:admin` header (returned 403). Two env vars on the Airflow service in `docker-compose.yml` make standalone trigger and CI trigger both work:

```yaml
- AIRFLOW__API__AUTH_BACKENDS=airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session
- AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=False
```

The first lets the REST API accept Basic Auth; the second prevents fresh DAGs from sitting in `paused` state on first registration (CI wipes `airflow_db` every run, so without this the DAG sat in `queued` indefinitely). Both fixes shipped on `main` at commit `e47d96f`; the pre-fix submission baseline is tagged `v1.0-submission`.

## FastAPI Backend (`backend/app/`)

- `main.py` — FastAPI app; loads model on startup via `lifespan`. Endpoints:
  - `POST /predict` — `{description}` → `{predicted_category, confidence, all_scores}`
  - `POST /predict/batch` — `{descriptions: [...]}` → `{results: [...], total}`
  - `GET /models` — list MLflow `bilstm_training` + `bilstm_finetune` FINISHED runs with metrics
  - `POST /models/switch` — zero-downtime model hot-swap from any MLflow run_id
  - `POST /feedback` — appends `{timestamp, description, predicted_category, actual_category, transaction_id, correct}` to `feedback/feedback.jsonl`
  - `GET /drift` — compares `actual_category` distribution in `feedback.jsonl` vs `feature_baseline.json`; flags >10pp shift; requires ≥100 samples; sets `DRIFT_SCORE` Prometheus gauge
  - `GET /metrics` — Prometheus exposition
  - `GET /health` / `GET /ready`
- `predictor.py` — `SpendSensePredictor` singleton. `load()` reads from disk paths set by env vars (`MODEL_PATH`, `VOCAB_PATH`, `LABEL_ENCODER_PATH`). `load_from_mlflow(run_id)` downloads artifacts to a tmpdir, expects model at `model/data/model.pth` within the artifact tree. Applies `torch.quantization.quantize_dynamic()` (INT8 on LSTM+Linear) **only on CPU**. `list_mlflow_runs()` filters to `bilstm_training` and `bilstm_finetune` run names only.
- `monitoring.py` — Prometheus metrics: `REQUEST_COUNT` (Counter, labels: endpoint/status), `REQUEST_LATENCY` (Histogram), `ERROR_RATE` (Gauge, rolling 100-request window), `PREDICTION_CATEGORY` (Counter), `MODEL_LOADED` (Gauge), `BATCH_SIZE` (Histogram), `FEEDBACK_TOTAL` (Counter), `DRIFT_SCORE` (Gauge), `MODEL_SWITCHES` (Counter)
- `schemas.py` — Pydantic models for all endpoints

## Streamlit Frontend (`frontend/`)

Three pages:
- **Home** (`Home.py`): single prediction, 6 example buttons that pre-fill the input, confidence bar chart, post-prediction feedback form (calls `POST /feedback`). Example buttons use `st.session_state.get("example_input")` (not `pop`) so the value survives the form-submit rerun; `pop` happens inside `if submitted:` only.
- **Batch Predict** (`pages/1_Batch_Predict.py`): three tabs — CSV upload, paste descriptions, HDFC bank statement XLS upload (auto-detects header row, filters withdrawal transactions). Results table, Altair donut chart, CSV download. HDFC narrations preprocessed by `_clean_hdfc_narration()` which strips UPI/NEFT/RTGS/etc. prefixes.
- **Pipeline Status** (`pages/2_Pipeline_Status.py`): health grid for all 7 services, live Prometheus metric counters, DVC DAG diagram via `dvc dag` + Graphviz, links to all tool UIs, Airflow DAG run history with task-level breakdown (queries Airflow REST API with Basic auth).

Frontend communicates with backend exclusively via `BACKEND_URL` env var. `PROMETHEUS_URL` and `ALERTMANAGER_URL` must use container names (`http://prometheus:9090`, `http://alertmanager:9093`) — `localhost` is unreachable inside Docker network.

## Airflow DAG (`airflow/dags/ingestion_dag.py`)

DAG ID: `spendsense_ingestion_pipeline`, `@daily`. Task chain:

```
verify_raw_data → validate_schema → check_nulls → check_drift → route_on_drift (BranchPythonOperator)
    ├── drift detected  → combine_data → run_ingest → trigger_dvc → pipeline_complete
    └── no drift        ─────────────────────────────────────────→ pipeline_complete
```

- `combine_data`: merges `data/raw/transactions_90.csv` + `data/drift/transactions_drift.csv` + `feedback/feedback.jsonl` (description/actual_category pairs) → `data/raw/transactions.csv`
- `run_ingest`: uses `shutil.rmtree(data/ingested/)` + `os.makedirs()` before running the subprocess to clear uid=1000 files that uid=50000 (Airflow user) cannot overwrite. No-op when `GITHUB_ACTIONS=true`.
- `trigger_dvc`: priority order — (1) `GITHUB_ACTIONS=true` → skip with `ci_context`; (2) `GITHUB_PAT` set → GitHub Actions `workflow_dispatch` against `main` with `run_full_pipeline=true`; (3) `LOCAL_DVC_REPRO=true` → run `dvc repro` in-process with optional `FINETUNE_MODEL_PATH` injection (note: airflow image lacks `dvc`/`torch`/`sklearn`, so this path requires extending `airflow/requirements.txt`); (4) otherwise → skip with `no_pat`. To enable standalone retraining via UI trigger, put `GITHUB_PAT=...` in a project-root `.env` file (already wired via `${GITHUB_PAT:-}` in compose).
- `pipeline_complete` uses `trigger_rule="none_failed_min_one_success"` — fires regardless of which branch was taken. **When drift was detected (XCom from `check_drift`), it sleeps 75s then pushes `pipeline_drift_detected=0`** so the `DataDriftDetected` alert fires exactly once per drift-positive run (allowing scrape ≤15s + eval ≤15s + Alertmanager `group_wait` 30s = ~60s end-to-end before email dispatch) and then resolves cleanly. DAG runtime: ~50s when no drift, ~120s when drift detected.
- All tasks push metrics to Prometheus Pushgateway via `_push_pipeline_metrics()`.

**Pushgateway metric semantics — critical:** `_push_pipeline_metrics` uses `pushadd_to_gateway` (POST), **not** `push_to_gateway` (PUT). PUT replaces *all* metric families for the job, so each task's push would wipe earlier tasks' metrics — `pipeline_complete=1` overwriting `pipeline_drift_detected=1` was the original cause of `DataDriftDetected` never firing. POST replaces only the families being pushed in that call, leaving others intact.

**Airflow container details:** `airflow/Dockerfile` installs from `apache/airflow:2.9.1-python3.10`. `airflow/entrypoint.sh` runs as root, does `chmod -R o+w /opt/airflow/project/data /opt/airflow/project/models`, then drops to airflow user (uid=50000) via `su -s /bin/bash airflow`. This is why `shutil.rmtree` works in task context (uid=50000 can unlink files in a world-writable non-sticky dir) but `os.chmod` of uid=1000 files fails with EPERM.

**DAG code is baked into the image, not bind-mounted.** `Dockerfile` does `COPY airflow/dags/ ${AIRFLOW_HOME}/dags/` and the `airflow_db` named volume mounts at `/opt/airflow`. After editing any file under `airflow/dags/`, you must `docker compose build airflow` *and* recreate the container with a fresh `airflow_db` volume — otherwise the old DAG code persists in the named volume:

```bash
docker compose build airflow
docker rm -f spendsense_airflow
docker volume rm da5402_project_airflow_db
docker compose up -d airflow
```

CI does this automatically (`docker compose build airflow` + the volume is wiped at start of every CI run via line 83 of ci.yml).

## Tests (`tests/`)

5 test files, ~50 tests total. Coverage excludes `train.py`, `evaluate.py`, `download_data.py` (require full DVC artifacts). Must meet 60% threshold.

| File | What it tests |
|---|---|
| `test_model.py` (7) | BiLSTM forward pass shapes, padding, backward pass, determinism |
| `test_ingest.py` (7) | Schema validation, null handling, category filtering, file output |
| `test_preprocess.py` (9) | Tokenization, vocab building, encoding, padding/truncation |
| `test_api.py` (25) | All FastAPI endpoints, predictor MLflow methods, error cases |
| `test_airflow_dag.py` (18) | All DAG task callables in isolation |

**Airflow test mock pattern:** The `airflow` package is stubbed in `sys.modules` at import time. Use `patch.object(dag_module.shutil, "rmtree")` and `patch.object(dag_module.os, "makedirs")` — NOT `@patch("airflow.dags.ingestion_dag.os.makedirs")` which fails because `airflow` is a stub module without a `dags` attribute.

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

**Instrumented components (5):** FastAPI backend (pull via `/metrics`), training pipeline, evaluation pipeline, Airflow DAG, Streamlit frontend — all push to Pushgateway.

**Alert rules (11):** `HighErrorRate` (>5%, 2m), `ModelNotLoaded` (1m), `HighPredictionLatency` (p95>500ms, 5m), `LowTestF1` (<0.70, instant), `LowValF1` (<0.65, instant), `TrainingDurationHigh` (>2h, instant), `DataDriftDetected` (instant), `IngestFailed` (instant), `FeedbackLoopDead` (no feedback in 24h, fires after 48h), `TailLatencySpike` (p99>1s, 5m), `FrequentModelSwitch` (>3/h, instant)

**Grafana panels (9, auto-provisioned):** Request Rate (req/s), Model Loaded, Predictions by Category, Total Requests, Latency Percentiles (P50/P95/P99), Airflow Drift Flag, Alert Firing History, Alerts Fired by Name (pie — `count_over_time(ALERTS{alertstate="firing"}[$__range])` summed by `alertname`), Recent Email Alerts (table of currently-firing alerts; all alerts route to email so no extra filter needed). Note: Grafana internal port is 3000, host port is 3001 — Docker inter-service config uses `grafana:3000`.

## Feedback Loop & Drift Detection

```
POST /feedback (description, predicted_category, actual_category)
    → feedback/feedback.jsonl  [persisted across CI runs]
    → GET /drift  detects distribution shift vs feature_baseline.json (≥100 samples, >10pp)
    → Airflow check_drift (@daily)  compares transactions_drift.csv vs baseline_stats.json
    → combine_data merges 90%+drift+feedback → run_ingest → trigger_dvc (retraining)
```

`feedback/feedback.jsonl` is bind-mounted into both the backend and Airflow containers. It persists across CI runs via explicit copy to/from runner's project directory in the CI workflow.

## Rollback Mechanisms

1. **Git + DVC:** `git checkout <commit> && dvc checkout` restores any prior pipeline state
2. **MLflow hot-swap:** `POST /models/switch` loads any prior run's model without container restart
3. **Full environment:** `docker compose down && git checkout <tag> && docker compose up`

## Key Invariants

- `FINETUNE_MODEL_PATH` in `train.py` switches Run 1 (full train, N epochs from params) vs Run 2 (fine-tune, always 1 epoch). Currently `params.yaml:train.epochs=1` so both runs train 1 epoch.
- `mlruns/` is bind-mounted into the MLflow container and persisted back to the project directory after each CI run. Only `mlruns/mlflow.db` is staged as the CI artifact (not the full `mlruns/` tree with binary model files).
- `feedback/feedback.jsonl` must be reset before a live demo for a clean `/drift` result — it accumulates CI test entries.
- **MLproject has known issues:** stale `generate` entry point and hyperparameter mismatch vs `params.yaml` — use `dvc repro` not `mlflow run .`.
- `data/drift/transactions_drift.csv` is the 10% intentionally skewed split polled by Airflow. `data/raw/transactions_90.csv` is the 90% baseline. Both are created by `scripts/create_drift_split.py` which oversamples the top-3 categories in the 10% slice to ensure >10pp distribution shift.
- Home page has no model-selection sidebar — use `POST /models/switch` API directly or the Pipeline Status page.
- `$RUNNER_TEMP` is cleaned between jobs on self-hosted GitHub Actions runners. Use `$HOME` for any path that must persist from Job 2 to Job 3.
- **Airflow container env determines task behaviour, not the host shell at trigger time.** `GITHUB_ACTIONS`/`GITHUB_PAT`/`LOCAL_DVC_REPRO` are read at *task execution* from the container's env, which is set when `docker compose up -d airflow` runs. CI runners have `GITHUB_ACTIONS=true` in their shell, so the airflow container they start has it baked in. Locally `GITHUB_ACTIONS` is unset → container sees `false` → `run_ingest` actually runs the subprocess and `trigger_dvc` skips with `no_pat` (unless you've put `GITHUB_PAT=...` in `.env`). To switch a running container between modes, `docker compose stop airflow && docker compose up -d airflow` from the appropriate shell.
- **`v1.0-submission` git tag** marks the pre-Airflow-fix submission baseline. Branch `fix/airflow-api-auth` was kept (not deleted) post-merge for evaluation walkthrough.
