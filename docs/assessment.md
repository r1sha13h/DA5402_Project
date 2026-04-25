# SpendSense — Compliance Assessment Report

**Project:** DA5402 MLOps — SpendSense: Personal Expense Category Classifier  
**Assessment Date:** 2026-04-25  
**Evaluated Against:** `docs/application guidelines.md` · `docs/evaluation guideline.md`  
**Latest CI Run:** #24928575305 — All 3 jobs passed · 67/67 unit tests · F1 = 0.9872  

---

## Summary Scorecard

| Evaluation Area | Max Pts | Estimated Score | Compliance |
|---|---|---|---|
| Demonstration — UI/UX | 6 | 5.5 | ✅ Strong |
| Demonstration — ML Pipeline Visualization | 4 | 3.5 | ✅ Good |
| Software Engineering — Design Principles | 2 | 2 | ✅ Full |
| Software Engineering — Implementation | 2 | 1.5 | ✅ Good |
| Software Engineering — Testing | 1 | 1 | ✅ Full |
| MLOps — Data Engineering | 2 | 2 | ✅ Full |
| MLOps — Source Control & CI | 2 | 2 | ✅ Full |
| MLOps — Experiment Tracking | 2 | 2 | ✅ Full |
| MLOps — Prometheus + Grafana | 2 | 1.75 | ✅ Good |
| MLOps — Software Packaging | 4 | 3.5 | ✅ Strong |
| **Total (excl. Viva)** | **27** | **26.25** | **97%** |

> Viva (8 pts) is performance-dependent and not assessed here.

---

## Section 1 — Demonstration (10 pts)

### 1A. Web Application UI/UX — 5.5/6

**What's implemented:**
- Streamlit multi-page app: Home (single predict), `1_Batch_Predict`, `2_Pipeline_Status`.
- Home page: text input, Classify button, 6 example buttons that pre-fill the input, confidence bar chart with `st.caption()` explaining softmax probability and low/high confidence thresholds, full score distribution across all 10 categories, post-prediction feedback form (calls `POST /feedback`).
- Batch prediction: three tabs — CSV upload (with column validation), paste descriptions, HDFC bank statement XLS upload (auto-detects header row, filters withdrawal transactions). Results table with category and confidence, Altair donut chart of category distribution, CSV download button.
- Pipeline Status page: live health grid for all 7 external services, live Prometheus metric counters with refresh, DVC pipeline DAG rendered via Graphviz (with ASCII fallback), direct links to all tool UIs.
- Sidebar: model readiness indicator, current MLflow run ID, model selection dropdown for hot-swap (calls `POST /models/switch`).
- User manual (`docs/user_manual.md`) covers all features in non-technical language.

**Strengths:**
- Loose coupling: Streamlit communicates exclusively via configurable `BACKEND_URL` REST calls — no shared code with backend.
- Non-technical accessibility: example buttons, `st.caption()` confidence explainer, category guide in user manual.
- Responsive to failures: model load error shown clearly, API errors surface as `st.error()` rather than crashes.
- HDFC XLS tab is a practical real-world feature that goes beyond rubric requirements.

**Gaps:**
- No mobile/responsive layout (Streamlit architectural constraint — defensible, documented in `docs/assessment.md §8`).
- Feedback form appears only after a prediction is made — new users may not discover it without guidance.

---

### 1B. ML Pipeline Visualization — 3.5/4

**What's implemented:**
- `2_Pipeline_Status` is the pipeline management console: service health grid, live metric counters, DVC DAG diagram, links to all tools.
- Airflow UI (port 8080): full 9-task DAG graph view with per-task logs, run history, and task duration timeline.
- MLflow UI (port 5000): all experiment runs, per-epoch metric curves, hyperparameters, artifacts including confusion matrix heatmap PNG.
- Grafana dashboard (port 3001): 17 panels covering request rates, latency percentiles, model state, feedback, drift, Airflow pipeline metrics, and model management.
- GitHub Actions run page: per-step pass/fail and timing for all 3 CI jobs.

**Gaps:**
- No error/failure history console within Streamlit itself — relies on Airflow UI and GitHub Actions for failure investigation.
- Pipeline visualization speed is limited by Airflow DAG trigger + `dvc dag` subprocess latency (sub-second for `dvc dag`, ~1s for Airflow health check). Acceptable.

---

## Section 2 — Software Engineering (5 pts)

### 2A. Design Principles — 2/2

**Fully compliant:**
- Architecture diagram: `docs/architecture.md` — layered ASCII diagram covering all 5 system layers.
- HLD: `docs/hld.md` — component breakdown, data flow, CI/CD design, ML model spec, security trade-offs, Grafana port 3001.
- LLD: `docs/lld.md` — all 9 API endpoints with request/response JSON schemas, field constraints, error codes, module function signatures, data models, exception handling table, logging standards.
- Loose coupling strictly enforced: frontend never imports backend code; communicates exclusively via REST calls to `BACKEND_URL`.
- OO paradigm: `SpendSensePredictor` class, `BiLSTMClassifier` nn.Module, Pydantic schema classes for all endpoint I/O.

---

### 2B. Implementation — 1.5/2

**What's implemented:**
- PEP8/flake8 enforced (max-line-length 100, CI gate passes with 0 issues).
- `logging` module used throughout all source files with consistent format string.
- Exception handling: `FileNotFoundError`/`ValueError` → `sys.exit(1)` in pipeline scripts; `RuntimeError` → HTTP 503, `Exception` → HTTP 500 in FastAPI; `requests.ConnectionError` handled in Streamlit.
- Google-style docstrings on all public functions with Args/Returns/Raises.
- Pydantic schemas enforce type and length validation on all API inputs.
- Dynamic INT8 quantization (`torch.quantization.quantize_dynamic`) applied to LSTM + Linear layers in `predictor.py` on CPU — reduces model memory ~4×.
- Confusion matrix heatmap PNG logged as MLflow artifact via `mlflow.log_artifact`.

**Gaps:**
- **`MLproject` stale `generate` entry point** — references `src/data/generate_synthetic.py` which no longer exists in the codebase. Running `mlflow run . -e generate` would fail. Remove this entry point before demo.
- `src/models/train.py` and `src/models/evaluate.py` are excluded from coverage in `setup.cfg` — defensible (require full DVC artefacts to run) but these are the most complex modules in the project and are untested at the unit level.
- Inline comments are sparse — complex logic in `task_check_drift`, `_process_hdfc_xls`, and `create_split` is not commented.

---

### 2C. Testing — 1/1

**Fully compliant:**
- Test plan: `docs/test_plan.md` — acceptance criteria (F1 ≥ 0.70, latency < 200ms, coverage ≥ 60%), test cases, pass/fail status.
- 5 test modules: `test_ingest.py`, `test_preprocess.py`, `test_model.py`, `test_api.py`, `test_airflow_dag.py`.
- 67 unit tests; all pass in CI (run 24928575305).
- Coverage: 66.3% (above 60% gate). CI enforces this threshold.
- Acceptance criteria formally verified: F1 gate via `sys.exit(1)` in `evaluate.py`; CI gate via `pytest --cov-fail-under=60`.

---

## Section 3 — MLOps Implementation (12 pts)

### 3A. Data Engineering — 2/2

**What's implemented:**
- Apache Airflow DAG (`airflow/dags/ingestion_dag.py`) — `spendsense_ingestion_pipeline`, 9 tasks:  
  `verify_raw_data → validate_schema → check_nulls → check_drift → route_on_drift → [combine_data → run_ingest → trigger_dvc] / [pipeline_complete]`
- `route_on_drift` is a `BranchPythonOperator`: routes to `combine_data` on drift, directly to `pipeline_complete` on no drift.
- `pipeline_complete` has `trigger_rule="none_failed_min_one_success"` — fires regardless of which branch was taken.
- Runs on `@daily` schedule; triggerable manually via Airflow UI or GitHub Actions `workflow_dispatch`.
- Drift detection: compares `transactions_drift.csv` category distribution vs. `baseline_stats.json` using per-category absolute shift (> 10 pp threshold). Flags categories with significant shift.
- When drift detected: `combine_data` merges 90% baseline + 10% drift file + `feedback.jsonl` corrections into combined `transactions.csv`. `run_ingest` validates and saves. `trigger_dvc` dispatches GitHub Actions to retrain (skipped with `GITHUB_ACTIONS=true` guard in CI).
- All tasks push pipeline metrics to Prometheus Pushgateway.
- `POST /feedback` endpoint logs ground-truth corrections to `feedback/feedback.jsonl` (timestamp, description, predicted, actual, correct flag).
- `GET /drift` endpoint reads feedback log, computes actual category distribution, compares vs `feature_baseline.json`, returns drift flags per category.

**Gaps:**
- No Apache Spark or Ray — Airflow alone satisfies the guidelines' "or" condition. Defensible at scale.
- Drift detection uses simple absolute shift (10 pp threshold), not a formal statistical test (chi-squared or KS test). Functionally sufficient for the dataset but less rigorous.

---

### 3B. Source Control & CI — 2/2

**Fully compliant:**
- Git for all code. DVC tracks `data/raw/`, `data/ingested/`, `data/processed/`, `models/`, `metrics/`.
- `dvc.yaml`: 4-stage DAG (`ingest → preprocess → train → evaluate`) with explicit deps, params, outs, metrics.
- `dvc.lock`: up to date and committed; pins all input/output hashes for full reproducibility.
- GitHub Actions CI: 3-job BAT pipeline (see `docs/ci_cd_pipeline.md` for full detail).
  - **Job 1:** flake8 + pytest + coverage gate.
  - **Job 2:** 90-10 drift split → infra services → DVC Run 1 (90% data) → F1 gate → Airflow → DVC Run 2 (fine-tune) → metrics persist.
  - **Job 3:** artifact download → backend+frontend Docker smoke tests.
- Self-hosted runner — no cloud compute.
- Every experiment reproducible via Git commit hash + MLflow run ID (enforced by MLflow auto-logging).

---

### 3C. Experiment Tracking — 2/2

**What's implemented:**
- MLflow experiment: `SpendSense`. Two run types: `bilstm_training` (Run 1) and `bilstm_finetune` (Run 2).
- **Parameters logged (10):** `embed_dim`, `hidden_dim`, `num_layers`, `dropout`, `batch_size`, `learning_rate`, `epochs`, `vocab_size`, `num_classes`, `seed`.
- **Metrics per epoch:** `train_loss`, `val_loss`, `train_f1_macro`, `val_f1_macro` (with step index).
- **Final metrics:** `test_accuracy`, `test_f1_macro`, `test_f1_weighted`, `best_val_f1_macro`.
- **Per-class F1** logged for all 10 categories individually (beyond autolog).
- **Artifacts:** model checkpoint (`.pt`), `vocab.pkl`, `label_encoder.pkl`, `params.yaml`, confusion matrix JSON, confusion matrix heatmap PNG.
- Training duration and val F1 pushed to Prometheus Pushgateway (job: `spendsense_training`). Evaluation metrics pushed post-evaluate (job: `spendsense_evaluate`).
- `MLproject` present with all 4 entry points; `python_env.yaml` pins training dependencies.
- Model registry auto-promotes new version to `Staging` via `MlflowClient.transition_model_version_stage()` after each training run.

**Gaps:**
- `MLproject` `generate` entry point is stale (references `src/data/generate_synthetic.py` which was removed). Remove before demo.
- The `main` entry point in `MLproject` uses default hyperparameter values that differ from `params.yaml` (e.g., `dropout: 0.3` in MLproject vs `0.75` in params.yaml). Running `mlflow run .` would use different hyperparameters than `dvc repro`. Should sync or remove custom defaults.

---

### 3D. Prometheus + Grafana — 1.75/2

**What's implemented:**
- FastAPI: 6 metrics via `backend/app/monitoring.py` — `requests_total`, `request_latency_seconds`, `error_rate`, `predictions_by_category_total`, `model_loaded`, `batch_size`, plus `feedback_total`, `drift_score`, `model_switches_total`.
- Pushgateway receives metrics from: training pipeline, evaluation pipeline, Airflow DAG, and Streamlit frontend.
- All 5 system components instrumented (backend, training, evaluation, Airflow, Streamlit).
- Prometheus scrapes backend every 10s; Pushgateway with `honor_labels: true`.
- **10 alert rules** in `monitoring/alert_rules.yml` across 4 groups: inference, training, pipeline, traffic. Includes `HighErrorRate > 5%` (rubric requirement), `DataDriftDetected`, `ModelNotLoaded`, `FeedbackLoopDead`.
- Alertmanager configured with Gmail SMTP routing (password via env var, not hardcoded).
- Grafana dashboard provisioned with 17 panels (auto-provisioned from JSON at startup).

**Gaps:**
- Grafana `prometheus.yml` has a `grafana` scrape job pointing to `grafana:3000` (the internal Docker port) — this is correct for inter-container communication but may confuse during demo since the host port is 3001.
- Pushgateway metrics for training and evaluation only populate during CI runs, not during local `docker compose up` without re-running the DVC pipeline. Noted in `docs/demo.md` — generate traffic with the provided curl commands before demo.

---

### 3E. Software Packaging — 3.5/4

**What's implemented:**
- **FastAPI backend:** Dockerized (`backend/Dockerfile`), Python 3.13-slim. Serves all 9 inference endpoints.
- **Streamlit frontend:** Dockerized (`frontend/Dockerfile`), separate service.
- **docker-compose.yml:** 8 services with healthchecks, env vars, volume mounts, inter-service dependencies. Backend depends on MLflow (healthy). Frontend depends on backend (healthy).
- **MLproject:** Present with `python_env.yaml` defining reproducible environment.
- **MLflow APIification:** `predictor.py`'s `load_from_mlflow(run_id)` downloads artefacts from the MLflow tracking server and loads the model for inference. Enables zero-downtime model hot-swap via `POST /models/switch`.
- Backend and frontend are strictly separate Docker services connected only via REST API at configurable `BACKEND_URL`.

**Gaps:**
- **`MLproject` stale `generate` entry point** (same as §2B gap — needs removal).
- `MLproject` default hyperparameters (embed_dim=128, batch_size=64, epochs=20, dropout=0.3) do not match `params.yaml` (batch_size=512, epochs=1, dropout=0.75). `mlflow run .` would produce a different model than `dvc repro`. Sync the defaults or document the divergence.
- No Docker Swarm configuration (guidelines say "if applicable" — single-node local deployment is acceptable for a prototype).

---

## Section 4 — Documentation (Required, not separately scored)

| Required Document | Status | File |
|---|---|---|
| Architecture diagram | ✅ Present | `docs/architecture.md` |
| High-Level Design (HLD) | ✅ Present | `docs/hld.md` |
| Low-Level Design (LLD) with API specs | ✅ Present | `docs/lld.md` |
| Test plan + test cases | ✅ Present | `docs/test_plan.md` |
| User manual (non-technical) | ✅ Present | `docs/user_manual.md` |
| CI/CD pipeline description | ✅ Present | `docs/ci_cd_pipeline.md` |
| E2E demo guide | ✅ Present | `docs/demo.md` |

---

## Section 5 — Guideline Compliance: Core Principles

| Principle | Status | Notes |
|---|---|---|
| Automation | ✅ | GitHub Actions + DVC automate full ML lifecycle |
| Reproducibility | ✅ | Git commit + MLflow run ID + `dvc.lock` tie every experiment |
| Continuous Integration | ✅ | 3-job GitHub Actions BAT pipeline, self-hosted runner, F1 gate |
| Monitoring & Logging | ✅ | All 5 components instrumented; 10 alert rules; structured logging throughout |
| Version Control | ✅ | Git for code, DVC for data/models, MLflow for experiments |
| Environment Parity | ✅ | Docker + docker-compose for production; `MLproject` + `python_env.yaml` for training |
| No Cloud | ✅ | All services local; self-hosted runner on local GPU |
| Encryption at rest/transit | ⚠️ | Dataset is public (no PII), deployment is localhost-only — defensible gap |
| Resource optimization | ✅ | Dynamic INT8 quantization on LSTM + Linear layers (CPU path) in `predictor.py` |
| Feedback loop (ground truth logging) | ✅ | `POST /feedback` appends to `feedback/feedback.jsonl`; `GET /drift` detects distribution shift |

---

## Section 6 — Open Issues Before Demo

### Critical
1. **`MLproject` stale `generate` entry point** — `src/data/generate_synthetic.py` no longer exists. Remove the `generate` entry point from `MLproject` to avoid `mlflow run . -e generate` failure during demo.
2. **`MLproject` hyperparameter mismatch** — Default values in `MLproject` (`batch_size=64`, `dropout=0.3`, `epochs=20`) differ from `params.yaml` (`batch_size=512`, `dropout=0.75`, `epochs=1`). Fix: either remove custom defaults from `MLproject` (so it reads from `params.yaml`) or update them to match.

### Minor
3. Grafana `prometheus.yml` scrape job for grafana uses `grafana:3000` — correct for Docker networking but worth noting during demo so evaluators don't confuse with host port 3001.
4. `feedback/feedback.jsonl` on the runner contains test entries from CI runs — reset or filter before demo if a clean feedback log is desired for the `/drift` demo.

---

## Section 7 — Defensible Gaps (Viva Answers)

| Gap | Viva Answer |
|---|---|
| No Apache Spark / Ray | Dataset is 4.5M rows and fits in pandas on a single machine. The guidelines list Spark/Ray as options alongside Airflow — Airflow satisfies the "or" condition. Spark would add significant operational complexity (cluster setup, YARN/Spark configuration) for no practical gain at this scale |
| No Docker Swarm | Guidelines state "if applicable". Single-node local deployment with docker-compose is the correct architecture for a prototype without multi-node HA requirements |
| No encryption | Dataset is publicly available on HuggingFace — no PII. All services communicate on a private Docker bridge network. In production, TLS termination would be added at an nginx reverse proxy layer without any application code changes |
| `train.py`/`evaluate.py` excluded from coverage | These scripts require the full DVC pipeline artifacts (4.5M row dataset, 10+ minute training run) to execute meaningfully. Mocking the training loop would test the mock, not the model logic. The 60% coverage gate is met with the remaining testable code |
| Mobile responsiveness | Streamlit uses fixed-width containers with no responsive breakpoint API. CSS injection via `st.markdown(unsafe_allow_html=True)` is possible but unreliable due to Streamlit's full-page re-render model |
| Drift detection uses 10 pp threshold, not chi-squared | Simple absolute shift is interpretable and matches the Airflow DAG documentation. A chi-squared test would require a minimum sample size assumption and would add complexity without improving the demo narrative |

---

## Section 8 — Strengths to Highlight in Demo

- **Real dataset, real metrics** — 4.5M HuggingFace transactions, 98.72% F1. Not synthetic.
- **Two-run DVC pipeline in CI** — Demonstrates the full drift detection + retraining loop end-to-end in a single CI run.
- **Alert rules matching rubric exactly** — `HighErrorRate > 5%` and `DataDriftDetected` are explicitly configured in `alert_rules.yml`.
- **Complete documentation suite** — All 5 required documents present plus `ci_cd_pipeline.md` and `demo.md`.
- **All 5 components instrumented** — Backend, training, evaluation, Airflow pipeline, and Streamlit frontend all push metrics.
- **Zero-downtime model hot-swap** — `/models/switch` loads any MLflow run's model without container restart.
- **Dynamic quantization** — INT8 quantization on CPU path reduces inference memory footprint ~4×.
- **9 Pydantic-validated endpoints** — Consistent schema enforcement with clear error codes across all API endpoints.
- **67 unit tests, 66.3% coverage** — Above the 60% CI gate; covering ingest, preprocess, model, API, and Airflow DAG modules.
