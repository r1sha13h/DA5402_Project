# SpendSense — Overhead Analysis & Mitigation

**Context:** CI run duration increased from ~26 minutes (single-run pipeline) to ~47–49 minutes (two-run pipeline with Airflow DAG) after the Change-1 design implementation. This document identifies which features drive that overhead, distinguishes required from optional work, and provides concrete mitigation strategies.

---

## CI Run Timing Breakdown (Run #24928575305)

| Step | Time | Required by Guidelines? |
|---|---|---|
| Create 90-10 drift split | 21s | No — CI-specific mechanism |
| Wait for Alertmanager healthy | 100s | No — email alerts are optional |
| DVC Run 1 (ingest→preprocess→train→evaluate on 90% data) | 356s | Partially — training required; two-run design is not |
| Verify Prometheus received training metrics | 21s | No — diagnostic only |
| Wait for Airflow healthy | 50s | Yes — Airflow is required |
| Trigger Airflow DAG + wait for completion | 603s | Yes — Airflow data pipeline required |
| DVC Run 2 (fine-tune on 90%+10% for 1 epoch) | 430s | No — single training run satisfies guidelines |
| Upload pipeline artifacts (Job 2 → Job 3) | 40s | Partially — only small artefacts needed |
| **Download pipeline artifacts (Job 3)** | **1219s (~20 min)** | Partially — only small artefacts needed |
| App services startup + smoke tests | ~120s | Yes |
| **Total** | **~47 min** | |

The previous single-run pipeline (before Change-1) ran in ~26 min. The delta (~21 min) is almost entirely explained by the two items in bold: DVC Run 2 (430s) and the artifact download in Job 3 (1219s).

---

## Features Present But Not Required by Guidelines

### 1. Two-run DVC pipeline (90-10 drift split + fine-tuning)

**What it is:** The CI pipeline splits the 4.5M row dataset 90/10, trains a baseline model on the 90% corpus (Run 1), triggers the Airflow DAG to detect drift and combine data, then fine-tunes the Run-1 model on the full 100% corpus (Run 2).

**Why it was added:** Demonstrates the full retraining loop end-to-end: data drift detection → data combination → model adaptation.

**Overhead:**
- Creates 3 extra large files: `transactions_90.csv` (146 MB), `transactions_drift.csv` (16 MB), combined `transactions.csv` (162 MB)
- DVC Run 2 adds ~430s of training + ~21s of evaluate
- Drift split creation adds ~21s

**Guideline requirement:** The guidelines require *a* training run and *a* drift detection mechanism. They do not require two sequential training runs in the same CI job.

**Mitigation options:**
- Run only a single DVC pipeline in CI; test drift detection by mocking the baseline stats in a unit test rather than running a full second training pass.
- OR: run Run 2 as a separate, non-blocking CI job (`needs: ml-pipeline`, `if: false` for routine pushes, `if: github.event_name == 'schedule'` for nightly runs).

---

### 2. Large numpy array artifacts uploaded/downloaded between jobs

**What it is:** Job 2 uploads `pipeline-artifacts` containing `models/`, `data/processed/`, `metrics/`, `mlruns/`. Job 3 downloads the full artifact set.

**Overhead:** The `data/processed/` directory is 276 MB:
- `X_train.npy`: 186 MB (4.05M × 50 token sequences × int32)
- `X_val.npy`: 40 MB
- `X_test.npy`: 40 MB
- `y_*.npy`: 11 MB total

Job 3 only needs: `models/latest_model.pt` (15 MB), `vocab.pkl` (101 KB), `label_encoder.pkl` (1 KB), `feature_baseline.json` (1 KB), and `mlruns/` for the `/models` endpoint test. The numpy arrays are never read by Job 3.

**Why it happens:** The artifact path in the workflow is `data/processed/` as a blanket directory. This was convenient during development but unnecessarily includes training data.

**Mitigation:** Scope the artifact upload to only what Job 3 needs:
```yaml
# In Job 2 upload step — replace:
path: |
  models/
  data/processed/
  metrics/
  mlruns/
  params.yaml

# With:
path: |
  models/latest_model.pt
  data/processed/vocab.pkl
  data/processed/label_encoder.pkl
  data/processed/feature_baseline.json
  metrics/
  mlruns/
  params.yaml
```
Estimated saving: ~270 MB of upload + ~270 MB of download → **eliminates ~15–18 minutes** from Job 3.

---

### 3. Alertmanager startup wait in Job 2

**What it is:** A 100s wait for Alertmanager to become healthy before continuing.

**Why it's slow:** Alertmanager's entrypoint runs `envsubst` on the config template and then starts the Go binary. On first start, this takes 60–90 seconds.

**Guideline requirement:** Alertmanager is part of the monitoring stack required by the guidelines. However, the 100s wait in the CI hot path is not required — Alertmanager health is not a prerequisite for DVC training.

**Mitigation:** Move the Alertmanager startup and smoke test to a parallel background step, or after DVC Run 1 completes. Alternatively, make the Alertmanager smoke test non-blocking (it already logs a warning rather than failing the build):
```yaml
- name: Start infra services
  run: |
    docker compose up -d mlflow pushgateway prometheus grafana
    # Start alertmanager in background — not needed for DVC training
    docker compose up -d alertmanager &
```
Estimated saving: **~80s** from the critical path.

---

### 4. Airflow DAG trigger wait (603s in Job 2)

**What it is:** After triggering the `spendsense_ingestion_pipeline` DAG, the workflow polls every 10s for up to 10 minutes waiting for `state == "success"`.

**Why it's slow:** The DAG runs all 9 tasks sequentially, including `run_ingest` which processes the combined 4.5M row dataset. Even with drift detected and `combine_data` running efficiently, the full DAG takes ~8–9 minutes.

**Guideline requirement:** The Airflow data pipeline is required. The 10-minute polling window is a safety margin.

**Mitigation options:**
- Reduce the polling interval from 10s to 5s — saves up to 45s in rounding overhead.
- Limit `run_ingest` in the Airflow DAG to process only a sample (e.g., first 100K rows) for validation purposes during CI runs, using an environment variable: `CI_SAMPLE_ROWS=100000`.
- Skip the `run_ingest` task in CI (`AIRFLOW__CORE__UNIT_TEST_MODE=True` or a DAG variable check) since DVC Run 2 re-runs ingest anyway — the Airflow DAG in CI only needs to verify the drift path is exercised and `combine_data` writes the combined file.
- Estimated saving if `run_ingest` is skipped in CI: **~3–4 minutes**.

---

### 5. Grafana dashboard with 17 panels

**What it is:** The Grafana dashboard (`monitoring/grafana/provisioning/dashboards/spendsense.json`) has 17 panels covering inference, training, evaluation, feedback, drift, Airflow, and model management metrics.

**Memory overhead:** Grafana itself uses ~100–150 MB RAM at idle. Each panel adds minimal overhead. The dashboard JSON is 41 KB.

**Guideline requirement:** Guidelines require "NRT visualization" with Prometheus/Grafana. 4–6 panels would satisfy the rubric. 17 panels exceeds requirements.

**Mitigation:** No runtime overhead worth optimizing — Grafana's memory footprint is dominated by the Go runtime, not panel count. The extra panels are a demonstration strength, not a problem.

---

### 6. HDFC XLS upload tab in Batch Predict

**What it is:** A third tab in the Batch Predict page that parses HDFC bank statement XLS files, auto-detects the header row, filters by date and withdrawal amount, and classifies transactions.

**Overhead:** Adds `xlrd>=2.0.1` and `openpyxl>=3.1.0` to `frontend/requirements.txt`. These are only imported inside the tab's code path — no startup overhead. Docker image build adds ~5s for the extra packages.

**Guideline requirement:** Not required. Added as a real-world usability feature.

**Mitigation:** None needed — the overhead is negligible.

---

### 7. Confusion matrix heatmap generation in evaluate.py

**What it is:** After evaluation, `src/models/evaluate.py` generates a matplotlib heatmap PNG of the 10×10 confusion matrix and logs it as an MLflow artifact.

**Memory and time overhead:** matplotlib loads ~50 MB of shared libraries on first import. Generating and saving a 10×10 heatmap takes ~2–3 seconds.

**Guideline requirement:** Guidelines require logging artifacts to MLflow (§3C). A confusion matrix JSON (already present) satisfies this. The heatmap is additional.

**Mitigation:** The overhead is minimal (3s). No action needed. If evaluate time were a bottleneck, wrapping the heatmap block in `if os.environ.get("GENERATE_CM_HEATMAP", "true") == "true":` would allow CI to skip it.

---

### 8. 10 alert rules in Alertmanager

**What it is:** `monitoring/alert_rules.yml` contains 10 alert rules across 4 groups: inference, training, pipeline, traffic.

**Overhead:** Prometheus evaluates all rule expressions every 15s. 10 simple rules add negligible CPU load.

**Guideline requirement:** Guidelines require "error rates exceed 5%" (`HighErrorRate`) and "data drift is detected" (`DataDriftDetected`). The remaining 8 rules (tail latency, model load, feedback loop, request rate, training duration, F1 thresholds) are additions.

**Mitigation:** No runtime overhead worth removing — rule evaluation is near-zero CPU. The extra rules are a demonstration strength.

---

### 9. Streamlit frontend Prometheus instrumentation

**What it is:** `frontend/monitoring.py` pushes `spendsense_ui_predictions_total`, `spendsense_ui_errors_total`, and `spendsense_ui_batch_items_total` to Pushgateway after each prediction.

**Overhead:** Each prediction adds ~50ms of network latency for the Pushgateway HTTP push (async-like in practice as it's non-blocking for the user). Adds `prometheus-client` (~2 MB) to the frontend Docker image.

**Guideline requirement:** Not explicitly required (the backend instrumentation alone satisfies the monitoring requirement). Added because "all components in your software that are being monitored" is a rubric criterion.

**Mitigation:** None needed — the overhead is negligible and the rubric coverage is worth it.

---

## Summary: What to Change to Reduce CI Runtime

Listed in order of impact:

| Change | Estimated Time Saved | Complexity |
|---|---|---|
| Scope artifact upload to exclude numpy arrays (276 MB → ~16 MB) | **~15–18 min** | Low — 5-line workflow edit |
| Remove DVC Run 2 from routine CI (run only on `main` pushes or scheduled) | **~7 min** | Medium — requires workflow condition logic |
| Skip `run_ingest` in Airflow DAG during CI runs | **~3–4 min** | Medium — requires DAG variable or env var check |
| Move Alertmanager startup off the critical path | **~80s** | Low — reorder `docker compose up` commands |
| Reduce Airflow poll interval from 10s to 5s | **~45s** | Low — one-line workflow edit |
| **Total potential saving** | **~26–30 min** | |

Applying just the first change (artifact scoping) would bring CI runtime from ~47 min back to ~27 min, matching the pre-Change-1 baseline, while retaining all functionality.

---

## Memory Overhead Summary

| Component | Memory Footprint | Notes |
|---|---|---|
| BiLSTM model (disk) | 15 MB | Quantized in-memory to ~4 MB (INT8 on CPU) |
| X_train.npy | 186 MB | Only needed during training; not needed by Job 3 |
| X_val.npy + X_test.npy | 80 MB | Only needed during training/evaluation |
| All Docker services combined | ~2–3 GB RAM | At idle with all 8 services running |
| Grafana | ~150 MB RAM | Dominated by Go runtime, not panel count |
| Airflow standalone | ~400–600 MB RAM | SQLite backend; standalone mode runs webserver + scheduler + triggerer |
| MLflow | ~200 MB RAM | SQLite backend |
| Prometheus | ~100 MB RAM | 7-day TSDB retention |
| FastAPI backend | ~300 MB RAM | Includes PyTorch runtime + quantized model |
| Streamlit frontend | ~200 MB RAM | Includes PyTorch (for potential local inference) + pandas |

**Largest single-run memory allocation:** `X_train.npy` at 186 MB — loaded into RAM during the DVC `preprocess` and `train` stages but never needed again after training completes.
