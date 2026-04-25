# SpendSense CI/CD Pipeline

**Workflow file:** `.github/workflows/ci.yml`  
**Runner:** Self-hosted (local GPU machine, no cloud)  
**Triggers:** Push to `main`/`develop`, pull request to `main`, `workflow_dispatch`  
**Architecture:** BAT — Build (Job 1) → Assess (Job 2) → Test (Job 3)

---

## Overview

```
┌─────────────────────────┐
│  Job 1: Lint & Tests    │  ~35s
│  (runs on every push)   │
└────────────┬────────────┘
             │ needs: test
┌────────────▼────────────────────────────────────────────┐
│  Job 2: ML Pipeline + Infra Services                    │  ~26 min
│  (runs on push to main or workflow_dispatch)            │
└────────────┬────────────────────────────────────────────┘
             │ needs: ml-pipeline
┌────────────▼────────────────────────────┐
│  Job 3: Streamlit & FastAPI Smoke Tests │  ~21 min
│  (runs on push to main only)            │
└─────────────────────────────────────────┘
```

---

## Job 1 — Lint & Unit Tests

**Purpose:** Fast feedback gate. Fails the build before any Docker or GPU work is done if code quality or tests regress.

| Step | What it does |
|---|---|
| Remove root-owned workspace files | Removes `mlruns/` which Docker may have written as root, preventing checkout failures |
| Checkout repository | `actions/checkout@v4` — fetches the pushed commit |
| Activate project venv | Sources the pre-installed project virtualenv; exports `PATH` and `VIRTUAL_ENV` into the job environment |
| Lint with flake8 | Runs `flake8 src/ backend/ tests/` — max line length 100, zero tolerance on errors. Covers all production and test code |
| Run unit tests with coverage | `pytest tests/ -v --cov=src --cov=backend --cov-report=term-missing --cov-fail-under=60` — runs all 67 unit tests across 5 modules; fails the build if coverage drops below 60% |

**Exit criteria:** All tests pass, flake8 reports 0 issues, coverage ≥ 60%.

---

## Job 2 — ML Pipeline + Infra Services

**Purpose:** End-to-end ML pipeline validation on real data with all infrastructure services running. Implements the BAT "Assess" layer — data in, trained+evaluated model out.

**Condition:** Only runs when `github.ref == refs/heads/main` or on `workflow_dispatch`. Skipped on PRs and develop branch pushes to save GPU time.

### Setup sub-tasks

| Step | What it does | Time |
|---|---|---|
| Remove root-owned workspace files | Same as Job 1 — clears Docker-written `mlruns/` | ~2s |
| Checkout repository | Fresh checkout | ~3s |
| Tear down leftover containers + stale Airflow volume | `docker compose down --remove-orphans` + removes `da5402_project_airflow_db` volume — ensures no port conflicts or stale SQLite lock files from prior runs | ~5s |
| Activate project venv | Sources venv; exports env vars | ~2s |
| Export host UID/GID | Sets `HOST_UID`/`HOST_GID` so Docker Compose containers write files with the runner's user ownership | ~1s |
| Verify torch + CUDA GPU | Asserts `torch.cuda.is_available()` — fails the build immediately if the GPU is unavailable rather than silently falling back to a 10× slower CPU training run | ~5s |

### Data preparation sub-tasks

| Step | What it does | Time |
|---|---|---|
| Ensure raw data exists | Checks `data/raw/transactions.csv`; if absent, copies from the runner's persistent project directory. The 164 MB dataset is not committed to Git — it lives on the runner | ~2s |
| Create 90-10 drift split | Runs `scripts/create_drift_split.py --verify` — stratified 90% baseline into `data/raw/transactions_90.csv`, skewed 10% (75% top-3 categories, with replacement) into `data/drift/transactions_drift.csv`, guaranteeing ≥ 10 pp distribution shift. Copies the 90% split over `transactions.csv` so DVC Run 1 trains on the baseline corpus | ~21s |
| Restore feedback.jsonl | Copies prior feedback entries from the runner's project directory into `feedback/feedback.jsonl` — persists the feedback loop state across CI runs | ~2s |

### Infrastructure startup sub-tasks

| Step | What it does | Time |
|---|---|---|
| Build infra Docker images | `docker compose build mlflow alertmanager pushgateway prometheus grafana` — uses Docker layer cache, typically a no-op unless Dockerfiles changed | ~5s cached |
| Pre-create mlruns directory | `mkdir -p mlruns/artifacts` owned by the runner user — prevents MLflow container from creating it as root | ~1s |
| Start infra services | `docker compose up -d mlflow alertmanager pushgateway prometheus grafana` — brings up 5 services on their respective ports (5000, 9093, 9091, 9090, 3001) | ~5s |
| Wait for MLflow healthy | Polls `http://localhost:5000/health` every 5s, up to 30 attempts (2.5 min max) | ~15s typical |
| Smoke test — MLflow | Single `curl` health check; fails build on non-200 | ~1s |
| Smoke test — Prometheus | `curl http://localhost:9090/-/healthy` | ~1s |
| Smoke test — Grafana | `curl http://localhost:3001/api/health` | ~1s |
| Wait for Alertmanager healthy | Polls `http://localhost:9093/-/healthy`, up to 20×5s = 100s | ~100s |
| Smoke test — Alertmanager | Non-fatal warning on failure (email alerts optional) | ~1s |
| Smoke test — Pushgateway | `curl http://localhost:9091/-/healthy` | ~1s |
| Restore MLflow runs | Copies `mlruns/` from the runner's project directory — preserves experiment history across CI runs so the MLflow UI always shows the full run timeline | ~3s |
| DVC pull cached stages | Attempts to pull cached DVC artifacts from remote; gracefully continues if no remote is configured | ~2s |

### DVC Run 1 sub-tasks (90% baseline training)

| Step | What it does | Time |
|---|---|---|
| Run DVC pipeline — Run 1 | `dvc repro` on the 90% baseline data: `ingest → preprocess → train → evaluate`. Trains the BiLSTM on ~4.05M rows (1 epoch), logs to MLflow, pushes metrics to Pushgateway | ~356s (~6 min) |
| Preserve Run-1 model | `cp models/latest_model.pt models/run1_model.pt` — saves the baseline checkpoint for use as the fine-tuning starting point in Run 2 | ~1s |
| Verify Prometheus metrics | Waits 20s for Pushgateway scrape, then queries Prometheus API for `spendsense_training_val_f1`, `spendsense_test_f1_macro`, `spendsense_test_accuracy`, `spendsense_training_duration_seconds` — warnings (not failures) if not yet visible | ~21s |
| Check evaluation metrics (Run 1) | Reads `metrics/eval_metrics.json`; fails the build if `test_f1_macro < 0.70` — the acceptance gate | ~2s |
| Push DVC artifacts | `dvc push` to remote cache — skipped gracefully if no remote configured | ~2s |

### Airflow sub-tasks (drift detection + data combination)

| Step | What it does | Time |
|---|---|---|
| Build Airflow Docker image | `docker compose build airflow` — builds the custom Airflow image with project DAGs, using layer cache | ~5s cached |
| Start Airflow service | `docker compose up -d airflow` — starts Airflow standalone (webserver + scheduler in one process) with SQLite backend | ~2s |
| Wait for Airflow healthy | Polls `http://localhost:8080/health` every 10s, up to 60 attempts (10 min max); fails with container logs dumped if timeout exceeded | ~50s typical |
| Smoke test — Airflow | Verifies Airflow is responding on port 8080 | ~1s |
| Trigger Airflow DAG | Calls `POST /api/v1/dags/spendsense_ingestion_pipeline/dagRuns` via Basic Auth (`admin:admin`). Polls DAG run state every 10s for up to 10 min. On success, `combine_data` task has merged 90%+10%+feedback into `data/raw/transactions.csv` for Run 2. On failure or timeout, falls back to a shell-based CSV concatenation to ensure Run 2 always has combined data | ~603s (~10 min) |

### DVC Run 2 sub-tasks (fine-tuning)

| Step | What it does | Time |
|---|---|---|
| Run DVC pipeline — Run 2 | `dvc repro --force` with `FINETUNE_MODEL_PATH=models/run1_model.pt` and `MLFLOW_TRACKING_URI=http://localhost:5000`. Loads Run-1 checkpoint, trains for 1 epoch on the combined ~4.5M row corpus, logs as `bilstm_finetune` run in MLflow | ~430s (~7 min) |

### Cleanup sub-tasks

| Step | What it does | Time |
|---|---|---|
| Save MLflow runs | Copies `mlruns/` back to the runner's project directory — persists all new run metadata for future CI runs and local inspection | ~3s |
| Persist feedback.jsonl | Copies updated `feedback/feedback.jsonl` back to the runner's project directory | ~1s |
| Upload pipeline artifacts | `actions/upload-artifact@v4` — uploads `models/`, `data/processed/`, `metrics/`, `mlruns/`, `params.yaml` for Job 3 to consume | ~40s |

**Exit criteria:** Both DVC runs complete with test F1 ≥ 0.70, all infra services healthy, Airflow DAG completes (or fallback succeeds).

---

## Job 3 — Streamlit & FastAPI Smoke Tests

**Purpose:** Validates that the trained model artefacts can be loaded by the application stack and that all user-facing endpoints respond correctly. Runs the application as it would in production.

**Condition:** Only runs on push to `main` (not `workflow_dispatch`).

| Step | What it does | Time |
|---|---|---|
| Checkout repository | Fresh checkout — no previous job's filesystem | ~3s |
| Download pipeline artifacts from Job 2 | Downloads `models/`, `data/processed/`, `metrics/`, `mlruns/` via `actions/download-artifact@v4` | ~1219s (~20 min) |
| Activate project venv | Sources venv | ~2s |
| Build app Docker images | `docker compose build backend frontend` | ~10s cached |
| Start app services | `docker compose up -d backend frontend` — backend depends on `mlflow` which is started transitively | ~5s |
| Wait for backend ready | Polls `http://localhost:8000/health`, up to 60×5s = 5 min | ~30s typical |
| Smoke test — /health | Asserts HTTP 200 | ~1s |
| Smoke test — /ready | Asserts HTTP 200 (model loaded) | ~1s |
| Smoke test — /predict | Posts `{"description": "Arby's Contactless"}`, asserts `predicted_category` and `confidence` fields present | ~1s |
| Smoke test — /models | Gets `/models`, asserts `runs` list is present | ~1s |
| Smoke test — /metrics | Gets `/metrics`, asserts `spendsense_` metric names are present | ~1s |
| Smoke test — Streamlit frontend | Polls `http://localhost:8501`, up to 20×5s = 100s, asserts HTTP 200 | ~30s typical |
| Tear down all services | `docker compose down` — always runs (`if: always()`) to clean up even on failure | ~5s |

**Exit criteria:** All smoke tests pass — model loads, prediction returns valid output, Prometheus metrics are exposed, Streamlit renders.

---

## Artifact flow between jobs

```
Job 2 uploads:
  models/latest_model.pt        (15 MB)
  models/run1_model.pt          (15 MB)
  data/processed/X_train.npy    (186 MB)
  data/processed/X_val.npy      (40 MB)
  data/processed/X_test.npy     (40 MB)
  data/processed/y_*.npy        (11 MB)
  data/processed/vocab.pkl      (101 KB)
  data/processed/label_encoder.pkl (1 KB)
  data/processed/feature_baseline.json (1 KB)
  metrics/                      (small)
  mlruns/                       (variable)
  params.yaml                   (small)

Job 3 actually uses:
  models/latest_model.pt
  data/processed/vocab.pkl
  data/processed/label_encoder.pkl
  data/processed/feature_baseline.json
  mlruns/ (for /models endpoint)
```

The numpy arrays (276 MB total) are uploaded and downloaded but not used by Job 3 — they are the primary cause of Job 3's 20-minute download time. See `docs/overhead.md` for mitigation.

---

## Key design decisions

**Why self-hosted runner?** The training step requires a CUDA GPU. GitHub-hosted runners are CPU-only and would require cloud GPU infrastructure, violating the project's no-cloud constraint.

**Why two DVC runs?** Run 1 establishes the baseline model on 90% of the data. The Airflow DAG then detects distribution drift in the held-out 10% and combines all data. Run 2 fine-tunes on the full corpus, demonstrating the retraining pipeline required by Application Guidelines §E.

**Why `dvc repro --force` on Run 2?** The input data (`transactions.csv`) has changed between runs (90% → 100%), so DVC would rerun anyway. `--force` is explicit about intent.

**Why `GITHUB_ACTIONS=true` in the Airflow DAG trigger step?** The `task_trigger_dvc` function in `ingestion_dag.py` checks this environment variable to skip the GitHub Actions `workflow_dispatch` REST call — the CI runner handles Run 2 directly, so a recursive dispatch would duplicate work.
