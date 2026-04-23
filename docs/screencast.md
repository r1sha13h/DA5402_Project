# SpendSense — Complete E2E Setup & Demo Guide

**Project:** DA5402 MLOps — Bidirectional LSTM Expense Classifier  
**Model metrics (latest run):** Test Accuracy 98.72% · F1 Macro 0.9872  
**Stack:** FastAPI · Streamlit · MLflow · Airflow · Prometheus · Grafana · Docker Compose · DVC

---

## Persistence Guarantee

Every service is configured to persist its state across `docker compose down / up` cycles:

| What | Where stored | Persists how |
|---|---|---|
| Trained model | `models/latest_model.pt` (local file) | Always — local filesystem |
| Preprocessed data / vocab | `data/processed/` (local files) | Always — local filesystem |
| MLflow experiment history | `mlruns/mlflow.db` (local file, bind-mounted) | Always — local filesystem |
| Feedback ground truth | `feedback/feedback.jsonl` (local file, bind-mounted) | Always — local filesystem |
| Prometheus time-series | `prometheus_data` (named Docker volume) | `docker compose down` only |
| Grafana dashboards & settings | `grafana_data` (named Docker volume) | `docker compose down` only |
| Airflow run history | `airflow_db` (named Docker volume) | `docker compose down` only |
| Pushgateway metrics | `pushgateway_data` (named Docker volume, `--persistence.file`) | `docker compose down` only |

> Use `docker compose down` (no `-v`) to preserve everything. Only use `docker compose down -v` when you want a completely clean reset.

---

## Prerequisites

```bash
# Required tools
docker --version        # Docker 24+
docker compose version  # Compose 2.x
git --version
dvc --version           # 3.x
python3 --version       # 3.11+
```

Clone and enter the repository:

```bash
git clone https://github.com/r1sha13h/DA5402_Project.git
cd DA5402_Project
```

---

## First-Time Setup (run once after fresh clone)

### Step A — Pull DVC artifacts

DVC-tracked files (model, data, processed splits) are not in Git. Pull them:

```bash
dvc pull
```

Expected outputs:
```
models/latest_model.pt         ~15 MB
data/raw/transactions.csv      ~180 MB
data/processed/vocab.pkl
data/processed/label_encoder.pkl
data/processed/feature_baseline.json
metrics/eval_metrics.json
```

If the DVC remote is not configured or artifacts are unavailable, run the full pipeline instead:

```bash
dvc repro
```

This runs all 4 stages: `ingest → preprocess → train → evaluate`. Takes ~20 minutes on first run.

### Step B — Verify artifacts

```bash
ls -lh models/latest_model.pt
ls data/processed/vocab.pkl data/processed/label_encoder.pkl
cat metrics/eval_metrics.json | python3 -m json.tool
```

Expected:
- `latest_model.pt` ~15 MB
- `test_accuracy: 0.9872`, `test_f1_macro: 0.9872`

### Step C — Create local directories (first time only)

```bash
mkdir -p feedback mlruns
```

These are bind-mounted into containers. Git-tracked via `.gitkeep`.

---

## Starting All Services

```bash
export HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose up --build -d
```

> First build: 5–10 min (downloads base images, installs dependencies).  
> Subsequent starts: ~30s (cached layers, existing volumes restored).

### Wait for healthy status

```bash
docker compose ps
```

All services should reach `healthy` or `running`:

| Container | Host Port | Status check |
|---|---|---|
| spendsense_mlflow | 5000 | `healthy` |
| spendsense_backend | 8000 | `healthy` |
| spendsense_frontend | 8501 | running |
| spendsense_airflow | 8080 | running |
| spendsense_prometheus | 9090 | running |
| spendsense_grafana | 3001 | running |
| spendsense_alertmanager | 9093 | running |
| spendsense_pushgateway | 9091 | running |

Quick sanity check:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
# Expected: {"status": "ok", "version": "1.0.0"}

curl -s http://localhost:8000/ready | python3 -m json.tool
# Expected: {"ready": true, "model_loaded": true, ...}
```

---

## Demo Walkthrough

### Step 1 — Streamlit Frontend (localhost:8501)

**Home page — Single Prediction**

1. Open `http://localhost:8501`
2. Type a transaction description:
   - `"Zomato food delivery payment"` → Food & Dining
   - `"Netflix monthly subscription"` → Entertainment & Recreation
   - `"BESCOM electricity bill"` → Utilities & Services
   - `"Apollo pharmacy purchase"` → Healthcare & Medical
   - `"SIP mutual fund investment"` → Financial Services
3. Note the **confidence caption** below the metric — explains softmax probability in plain English.
4. Point out the score distribution bars for all 10 categories.
5. Use the 6 quick-example buttons to demo without typing.

**Page 1 — Batch Prediction**

1. Navigate to `1_Batch_Predict`
2. Paste tab → enter these descriptions:
```
Zomato food delivery
Uber ride booking
Amazon shopping cart
Netflix subscription
Apollo pharmacy
BESCOM electricity bill
SIP investment
Tax payment
NGO donation
Salary credit
```
3. Show the results table, category distribution bar chart, and CSV download.

**Page 2 — Pipeline Status**

1. Navigate to `2_Pipeline_Status`
2. Show the 4-service health grid (Backend / MLflow / Airflow / Grafana).
3. Click **"🔄 Refresh Metrics"** → show live Prometheus counter values.
4. Show the DVC pipeline DAG rendered inline (click "🔄 Render DAG" for live output).
5. Show the MLflow / Airflow / Grafana links.

**Sidebar — Model Selection**

1. Show the MLflow run dropdown — lists all past training runs with F1 score and timestamp.
2. Select a run and click "🚀 Load this model" to hot-swap the active model without restart.

---

### Step 2 — FastAPI Swagger UI (localhost:8000/docs)

1. Open `http://localhost:8000/docs`
2. **POST /predict** → Try it out → `{"description": "Swiggy order payment"}` → Execute
3. **POST /predict/batch** → Try it out → `{"descriptions": ["Uber ride", "Netflix"]}` → Execute
4. **GET /models** → shows all MLflow runs available for switching
5. **POST /feedback** → submit a ground truth label:
   ```json
   {
     "description": "Zomato food delivery",
     "predicted_category": "Food & Dining",
     "actual_category": "Food & Dining"
   }
   ```
6. **GET /drift** → shows category distribution comparison between feedback and training baseline
7. **GET /ready** → confirms model loaded and quantized

---

### Step 3 — MLflow Tracking (localhost:5000)

> All experiment history is in `mlruns/mlflow.db` — mounted into the container — survives every restart.

1. Open `http://localhost:5000`
2. Click experiment **SpendSense**
3. Click the latest run (`bilstm_training`) — show:
   - **Parameters:** embed_dim, hidden_dim, learning_rate, batch_size, vocab_size
   - **Metrics:** per-epoch train_loss, val_loss, train_f1_macro, val_f1_macro (line charts)
   - **Artifacts:** model checkpoint, vocab.pkl, label_encoder.pkl, params.yaml
4. Navigate to **Models** tab → show `SpendSense` registered model → latest version in **Staging** (auto-promoted by `train.py`)

---

### Step 4 — Airflow DAG (localhost:8080)

**Credentials:** admin / admin

1. Open `http://localhost:8080`
2. Find DAG `spendsense_ingestion_pipeline`
3. Show the DAG graph:
   ```
   verify_raw_data → validate_schema → check_nulls → check_drift → run_ingest → trigger_dvc
   ```
4. Trigger a manual run → watch tasks turn green
5. Click `check_drift` → **Logs** → show distribution comparison against baseline
6. Point out: drift detection pushes `spendsense_pipeline_drift_detected` to Pushgateway

---

### Step 5 — Prometheus + Grafana Monitoring

**Generate traffic first:**

```bash
for desc in "Zomato delivery" "Uber ride" "Netflix" "Apollo pharmacy" "BESCOM bill" \
            "Amazon order" "SIP investment" "Tax payment" "Salary credit" "NGO donation" \
            "Swiggy food" "Ola cab" "Spotify premium" "BookMyShow" "Flipkart purchase" \
            "Lab test" "Credit card payment" "Passport fees" "Temple donation" "Freelance payment"; do
  curl -s -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d "{\"description\": \"$desc\"}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['description'],'→',d['predicted_category'])"
done
```

**Prometheus (localhost:9090)**

1. Open `http://localhost:9090`
2. Query `spendsense_requests_total` → counts by endpoint
3. Query `spendsense_request_latency_seconds_bucket` → latency distribution
4. Query `spendsense_test_f1_macro` → model quality from last CI run
5. Query `spendsense_ui_predictions_total` → Streamlit UI prediction count (Pushgateway)
6. Query `spendsense_pipeline_drift_detected` → Airflow drift flag (Pushgateway)

> **Pushgateway note:** `spendsense_test_f1_macro`, `spendsense_training_val_f1`, and
> `spendsense_pipeline_*` populate after a full `dvc repro` run with Docker up.
> `spendsense_ui_*` populate after any prediction via the Streamlit UI.
> All Pushgateway metrics persist across restarts via the `pushgateway_data` volume.

**Grafana (localhost:3001)**

**Credentials:** admin / admin

1. Open `http://localhost:3001`
2. Go to **Dashboards → SpendSense → SpendSense — MLOps Dashboard**
3. Walk through panels:
   - **Request Rate** — requests/sec over time
   - **P95 Latency** — 95th percentile latency
   - **Error Rate** — gauge (alert fires if > 5%)
   - **Predictions by Category** — bar chart

---

### Step 6 — End-to-End Data Flow Narrative

```
Raw CSV (data/raw/transactions.csv)
  ↓  Airflow DAG: schema check → null check → drift detect → ingest
  ↓  src/data/ingest.py → data/ingested/transactions.csv
  ↓  src/data/preprocess.py → data/processed/ (vocab, splits, baseline)
  ↓  src/models/train.py → models/latest_model.pt + MLflow run → auto-Staging
  ↓  src/models/evaluate.py → metrics/eval_metrics.json (F1 ≥ 0.70 gate)
  ↓  FastAPI loads model, applies INT8 quantization on CPU
  ↓  Streamlit → POST /predict → FastAPI → category + confidence
  ↓  POST /feedback → feedback.jsonl → GET /drift → distribution shift check
  ↓  Prometheus scrapes /metrics every 10s → Grafana NRT dashboard
  ↓  GitHub Actions CI runs this entire flow on every push to main
```

---

## Stopping Services

```bash
# Preserve all state (use this normally)
docker compose down

# Full reset — wipes Docker volumes (Grafana, Prometheus, Airflow, Pushgateway)
# MLflow history, model, data, and feedback survive (they're local files)
docker compose down -v
```

---

## Subsequent Starts (after first-time setup)

No DVC pull or rebuild needed unless code changed:

```bash
export HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose up -d
```

All previous MLflow runs, Grafana dashboards, Airflow run history, Prometheus metrics, and feedback data are automatically restored from volumes and bind-mounts.

If you pulled new code:

```bash
git pull
docker compose up --build -d   # rebuild images with new code
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Backend shows `model_loaded: false` | Check `models/latest_model.pt` exists; run `dvc pull` or `dvc repro` |
| MLflow shows no runs | `mlruns/mlflow.db` may be missing — run `dvc repro` to regenerate |
| Grafana panels show "No data" | Make some predictions first; Pushgateway metrics need a `dvc repro` to populate |
| Airflow shows no DAG | Wait 60s for Airflow scheduler to pick up DAGs from the container image |
| `docker compose up` fails on port conflict | Another process uses port 8000/5000/8501. Stop it or change the host port in docker-compose.yml |
| Feedback not persisting | Ensure `feedback/` directory exists locally; check backend volume mount |
