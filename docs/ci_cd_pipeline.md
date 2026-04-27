# SpendSense CI/CD Pipeline

**Workflow file:** `.github/workflows/ci.yml`
**Runner:** Self-hosted (local GPU machine, no cloud)
**Triggers:** Push to `main`/`develop`, pull request to `main`, `workflow_dispatch`
**Architecture:** BAT — Build (Job 1) → Assess (Job 2) → Test (Job 3)

---

## Overview

```
┌─────────────────────────┐
│  Job 1: Lint & Tests    │  ~40s
│  (runs on every push)   │
└────────────┬────────────┘
             │ needs: test
┌────────────▼────────────────────────────────────────────┐
│  Job 2: ML Pipeline + Infra Services                    │  ~11 min
│  (runs on push to main or workflow_dispatch)            │
└────────────┬────────────────────────────────────────────┘
             │ needs: ml-pipeline
┌────────────▼────────────────────────────┐
│  Job 3: Streamlit & FastAPI Smoke Tests │  ~1.5 min
│  (runs on push to main only)            │
└─────────────────────────────────────────┘
```

Total end-to-end: ~13 minutes (verified against latest run `24983169791`).

Observed per-job timings on the self-hosted RTX 3060 Laptop runner:

| Job | Wall-clock | Wait time |
|---|---|---|
| Job 1 — Lint & Tests | ~30 s | n/a |
| Job 2 — ML Pipeline + Infra | ~11.5 min | dominated by 2 × BiLSTM training passes (~3 min each) |
| Job 3 — Smoke Tests | ~1 min | n/a |

---

## Job 1 — Lint & Unit Tests

**Purpose:** Fast feedback gate. Fails the build before any Docker or GPU work is done if code quality or tests regress.

| Step | What it does |
|---|---|
| Remove root-owned workspace files | Removes `mlruns/` which Docker may have written as root, preventing checkout failures |
| Checkout repository | `actions/checkout@v4` — fetches the pushed commit |
| Activate project venv | Sources the pre-installed project virtualenv; exports `PATH` and `VIRTUAL_ENV` into the job environment |
| Lint with flake8 | Runs `flake8 src/ backend/ tests/` — max line length 100, zero tolerance on errors |
| Run unit tests with coverage | `pytest tests/ -v --cov=src --cov=backend --cov-fail-under=60` — runs all 68 unit tests; fails if coverage drops below 60% |

**Exit criteria:** All 68 tests pass, flake8 reports 0 issues, coverage ≥ 60%.

---

## Job 2 — ML Pipeline + Infra Services

**Purpose:** End-to-end ML pipeline validation on real data with all infrastructure services running. Implements the BAT "Assess" layer — data in, trained+evaluated model out.

**Condition:** Only runs when `github.ref == refs/heads/main` or on `workflow_dispatch`. Skipped on PRs and develop branch pushes to save GPU time.

### Setup

| Step | What it does | Time |
|---|---|---|
| Remove root-owned workspace files | Clears Docker-written `mlruns/` | ~2s |
| Checkout repository | Fresh checkout | ~3s |
| Tear down leftover containers + stale Airflow volume | `docker compose down --remove-orphans` + removes `da5402_project_airflow_db` volume | ~5s |
| Activate project venv | Sources venv; exports env vars | ~2s |
| Export host UID/GID | Sets `HOST_UID`/`HOST_GID` so Docker Compose containers write files with runner's user ownership | ~1s |
| Verify torch + CUDA GPU | Asserts `torch.cuda.is_available()` — fails immediately if GPU unavailable | ~4s |

### Data preparation

| Step | What it does | Time |
|---|---|---|
| Ensure raw data exists | Checks `data/raw/transactions.csv`; copies from runner's persistent project dir if absent | ~2s |
| Create 90-10 drift split | `scripts/create_drift_split.py --verify` — stratified 90% baseline into `transactions_90.csv`, intentionally skewed 10% (75% top-3 categories, with replacement) into `transactions_drift.csv`. Copies 90% split over `transactions.csv` for DVC Run 1 | ~4s |
| Restore feedback.jsonl | Copies prior feedback entries from runner's project directory | ~2s |

### Infrastructure startup

| Step | What it does | Time |
|---|---|---|
| Build infra Docker images | `docker compose build mlflow alertmanager pushgateway prometheus grafana` — uses layer cache | ~5s cached |
| Pre-create mlruns directory | `mkdir -p mlruns/artifacts` owned by runner user | ~1s |
| Start infra services | `docker compose up -d mlflow alertmanager pushgateway prometheus grafana` | ~5s |
| Wait for MLflow healthy | Polls `http://localhost:5000/health` every 5s, up to 30 attempts | ~10s typical |
| Smoke tests — MLflow, Prometheus, Grafana, Alertmanager, Pushgateway | Single `curl` health check per service | ~5s total |
| Restore MLflow runs | Copies `mlruns/` from runner's project dir — preserves experiment history | ~3s |
| DVC pull cached stages | Attempts to pull cached DVC artifacts from remote | ~2s |

### DVC Run 1 (90% baseline training)

| Step | What it does | Time |
|---|---|---|
| Run DVC pipeline — Run 1 | `dvc repro` on 90% baseline data (1,209,118 rows): `ingest → preprocess → train → evaluate`. Full BiLSTM training, logs to MLflow as `bilstm_training`, pushes metrics to Pushgateway | ~178s |
| Preserve Run-1 model | `cp models/latest_model.pt models/run1_model.pt` — saves baseline checkpoint for Run 2 fine-tuning | ~1s |
| Build Airflow Docker image | `docker compose build airflow` — started here (before Prometheus verify) so the healthcheck wait overlaps with subsequent steps | ~5s cached |
| Start Airflow service | `docker compose up -d airflow` | ~2s |
| Verify Prometheus metrics | Queries Prometheus API for `spendsense_training_val_f1`, `spendsense_test_f1_macro`, `spendsense_test_accuracy`, `spendsense_training_duration_seconds` — warnings only (non-fatal) if not yet visible | ~1s |
| Check evaluation metrics (Run 1) | Reads `metrics/eval_metrics.json`; **fails the build** if `test_f1_macro < 0.70` | ~2s |
| Push DVC artifacts | `dvc push` to remote cache — skipped gracefully if no remote | ~2s |

### Airflow (drift detection + data combination)

| Step | What it does | Time |
|---|---|---|
| Wait for Airflow healthy | Polls `http://localhost:8080/health` every 10s, up to 60 attempts; by this point Airflow has been starting for ~20s so wait is short | ~20s typical |
| Smoke test — Airflow | Verifies Airflow on port 8080 | ~1s |
| Trigger Airflow DAG | `POST /api/v1/dags/spendsense_ingestion_pipeline/dagRuns` via Basic Auth (`admin:admin`). Polls DAG state every 5 s for up to 40 iterations (~3.3 min budget). On success `combine_data` has merged 90% + 10% + feedback into `transactions.csv` (~1.28 M rows). On failure uses shell-fallback merge | ~60 s typical |

### DVC Run 2 (fine-tuning on combined data)

| Step | What it does | Time |
|---|---|---|
| Run DVC pipeline — Run 2 | `dvc repro --force` with `FINETUNE_MODEL_PATH=models/run1_model.pt`. Loads Run-1 checkpoint, fine-tunes for 1 epoch on combined corpus, logs as `bilstm_finetune` in MLflow | ~191s |

### Cleanup

| Step | What it does | Time |
|---|---|---|
| Save MLflow runs | Copies `mlruns/` back to runner's project dir — persists run history | ~3s |
| Persist feedback.jsonl | Copies updated feedback log to runner's project dir | ~1s |
| Upload pipeline artifacts | `actions/upload-artifact@v4` — uploads scoped artifact set for Job 3 | ~17s |

**Exit criteria:** Both DVC runs complete with test F1 ≥ 0.70, all infra services healthy, Airflow DAG completes (or fallback succeeds).

---

## Job 3 — Streamlit & FastAPI Smoke Tests

**Purpose:** Validates that the trained model artifacts can be loaded by the application stack and all user-facing endpoints respond correctly.

**Condition:** Only runs on push to `main` (not `workflow_dispatch`).

| Step | What it does | Time |
|---|---|---|
| Checkout repository | Fresh checkout | ~3s |
| Download pipeline artifacts from Job 2 | `actions/download-artifact@v4` — downloads scoped artifact set | ~40s |
| Activate project venv | Sources venv | ~2s |
| Build app Docker images | `docker compose build backend frontend` | ~10s cached |
| Start app services | `docker compose up -d backend frontend` | ~5s |
| Wait for backend ready | Polls `http://localhost:8000/health`, up to 60×5s | ~15s typical |
| Smoke test — /health | Asserts HTTP 200 | ~1s |
| Smoke test — /ready | Asserts HTTP 200 (model loaded) | ~1s |
| Smoke test — /predict | Posts `{"description": "Arby's Contactless"}`, asserts `predicted_category` + `confidence` present | ~1s |
| Smoke test — /models | Gets `/models`, asserts `runs` list present | ~1s |
| Smoke test — /metrics | Gets `/metrics`, asserts `spendsense_` names present | ~1s |
| Smoke test — Streamlit frontend | Polls `http://localhost:8501`, up to 20×5s | ~15s typical |
| Tear down all services | `docker compose down` — always runs (`if: always()`) | ~5s |

**Exit criteria:** All smoke tests pass — model loads, prediction returns valid output, Prometheus metrics exposed, Streamlit renders.

---

## Artifact flow between jobs

```
Job 2 uploads (total ~30 MB):
  models/latest_model.pt              (~15 MB)  ← used by Job 3 backend
  data/processed/vocab.pkl            (~101 KB) ← used by Job 3 backend
  data/processed/label_encoder.pkl    (~1 KB)   ← used by Job 3 backend
  data/processed/feature_baseline.json (~1 KB)  ← used by Job 3 /drift endpoint
  mlruns/mlflow.db                    (~1 MB)   ← used by Job 3 /models endpoint
  params.yaml                         (~1 KB)   ← metadata

Not uploaded (stays in Job 2 only):
  models/run1_model.pt    — only used within Job 2 for fine-tuning
  data/processed/*.npy    — numpy arrays not needed by Job 3 (276 MB avoided)
  metrics/                — eval metrics checked in Job 2; not used by Job 3
```

Job 3 loads the model via `MODEL_PATH=/app/models/latest_model.pt` volume mount — it does **not** use the MLflow artifact store for model loading.

---

## Key design decisions

**Why self-hosted runner?** Training requires a CUDA GPU. GitHub-hosted runners are CPU-only, violating the no-cloud constraint.

**Why two DVC runs?** Run 1 establishes a baseline model on 90% of the data. Airflow detects distribution drift in the held-out 10% and combines all data. Run 2 fine-tunes on the full corpus — demonstrating the complete retraining pipeline required by Application Guidelines §E.

**Why `dvc repro --force` on Run 2?** Input data changed (90% → 100% combined), so `--force` makes intent explicit even though DVC would rerun anyway.

**Why `GITHUB_ACTIONS=true` forwarded to Airflow?** Three task callables check this env var:
- `task_run_ingest` returns immediately with `{skipped: True, reason: ci_mode}` (DVC Run 2 re-runs ingest anyway)
- `task_trigger_dvc` skips with `ci_context` (the runner drives DVC Run 2 directly)
- `task_pipeline_complete` skips the 75 s alert-fire-and-resolve wait (the whole stack is torn down right after the run, so the alert auto-resolves anyway). This skip alone saves ~165 s vs running the wait in CI.

All three short-circuits avoid redundant work without changing the DAG topology, so the same DAG file runs identically locally for demos.

**Why Airflow build/start is moved before the Prometheus verify step?** Airflow takes ~40 s to become healthy. Starting it before the Prometheus verify + metric check + DVC push steps (~25 s combined) means the healthcheck wait is effectively free, saving ~20 s of serial waiting.

**Why Basic Auth needs explicit env vars on the Airflow service?** Airflow 2.9 defaults to session-only auth and silently rejects `Authorization: Basic admin:admin` headers (returns 403). The `docker-compose.yml` Airflow service sets:

```yaml
- AIRFLOW__API__AUTH_BACKENDS=airflow.api.auth.backend.basic_auth,airflow.api.auth.backend.session
- AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=False
```

The first lets the REST API accept Basic Auth (so CI's curl trigger works); the second prevents fresh DAGs from sitting in `paused` state on first registration (CI wipes `airflow_db` every run, so without this flag the DAG would sit `queued` indefinitely).
