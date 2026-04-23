# SpendSense — Live Demo Screencast Guide

**Project:** DA5402 MLOps — Bidirectional LSTM Expense Classifier  
**Model metrics (latest run):** Test Accuracy 98.72% · F1 Macro 0.9872  
**Stack:** FastAPI · Streamlit · MLflow · Airflow · Prometheus · Grafana · Docker Compose

---

## Pre-flight Checklist

Run these before starting the demo. All should pass.

```bash
cd /home/rishabh/Documents/IITM/MLOps/Project/DA5402_Project

# Trained model
ls -lh models/latest_model.pt

# Preprocessed data & vocab
ls data/processed/vocab.pkl data/processed/label_encoder.pkl

# MLflow DB (carries all previous run history)
ls -lh mlruns/mlflow.db

# Evaluation metrics from latest run
cat metrics/eval_metrics.json | python3 -m json.tool | grep -E "accuracy|f1_macro"
```

Expected:
- `latest_model.pt` ~15 MB
- `vocab.pkl` and `label_encoder.pkl` present
- `mlflow.db` present (this file carries all experiment history into the container)
- `test_accuracy: 0.9872`, `test_f1_macro: 0.9872`

---

## Step 1 — Start All Services

```bash
cd /home/rishabh/Documents/IITM/MLOps/Project/DA5402_Project

# Export your user ID so Docker writes files as you, not root
export HOST_UID=$(id -u) HOST_GID=$(id -g)

# Start everything
docker compose up --build -d
```

> First build takes 5–10 min. Subsequent starts use cached layers and take ~30s.

Watch services come up:

```bash
docker compose ps
```

Wait until all show `healthy` or `running`:

| Container | Port | Ready when |
|---|---|---|
| spendsense_mlflow | 5000 | `healthy` |
| spendsense_backend | 8000 | `healthy` |
| spendsense_frontend | 8501 | running |
| spendsense_airflow | 8080 | running |
| spendsense_prometheus | 9090 | running |
| spendsense_grafana | 3001 | running |
| spendsense_alertmanager | 9093 | running |
| spendsense_pushgateway | 9091 | running |

Quick health check:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
curl -s http://localhost:8000/ready  | python3 -m json.tool
```

---

## Step 2 — Demo: Streamlit Frontend (localhost:8501)

**Home page — Single Prediction**

1. Open `http://localhost:8501`
2. Type a transaction description, e.g.:
   - `"Zomato food delivery payment"` → Food & Dining
   - `"Netflix monthly subscription"` → Entertainment & Recreation
   - `"BESCOM electricity bill"` → Utilities & Services
   - `"Apollo pharmacy purchase"` → Healthcare & Medical
   - `"SIP mutual fund investment"` → Financial Services
3. Show the confidence bar chart — point out near-100% confidence on clear transactions

**Page 1 — Batch Prediction**

1. Navigate to `1_Batch_Predict`
2. Paste or upload a CSV with a `description` column
3. Show the downloadable results table with categories + confidence scores

Sample CSV content to paste:
```
description
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

**Page 2 — Pipeline Status**

1. Navigate to `2_Pipeline_Status`
2. Show backend health, MLflow URL, live metrics

---

## Step 3 — Demo: FastAPI (localhost:8000/docs)

1. Open `http://localhost:8000/docs`
2. Show the Swagger UI — expand `POST /predict`
3. Click **Try it out** → enter `{"description": "Swiggy order payment"}`
4. Execute → show response with `predicted_category`, `confidence`, `all_scores`
5. Expand `POST /predict/batch` → show batch endpoint
6. Expand `GET /models` → show MLflow run listing (previous runs loaded from `mlruns/mlflow.db`)

---

## Step 4 — Demo: MLflow Tracking (localhost:5000)

> All previous experiment runs are persisted in `mlruns/mlflow.db` which is mounted into the container — history survives restarts.

1. Open `http://localhost:5000`
2. Click experiment **SpendSense**
3. Show the list of runs — each row is one `dvc repro` execution
4. Click the latest run (`bilstm_training`)
5. Show:
   - **Parameters:** embed_dim, hidden_dim, learning_rate, batch_size, epochs, vocab_size
   - **Metrics:** per-epoch train_loss, val_loss, train_f1_macro, val_f1_macro
   - **Artifacts:** model checkpoint, vocab.pkl, label_encoder.pkl, params.yaml
6. Navigate to **Models** tab → show `SpendSense` registered model → latest version in Production

---

## Step 5 — Demo: Airflow DAG (localhost:8080)

**Credentials:** admin / admin

1. Open `http://localhost:8080`
2. Find DAG `spendsense_ingestion_pipeline`
3. Show the DAG graph view — 6 tasks in sequence:
   ```
   verify_raw_data → validate_schema → check_nulls → check_drift → run_ingest → trigger_dvc
   ```
4. Click each task node and show the docstring / description
5. Trigger a manual run — click ▶ (play button)
6. Watch tasks go green one by one
7. Click `check_drift` → **Logs** → show the drift detection output comparing current distribution to baseline

---

## Step 6 — Demo: Prometheus + Grafana Monitoring

**Prometheus (localhost:9090)**

1. Open `http://localhost:9090`
2. Query `spendsense_requests_total` → show request counts by endpoint
3. Query `spendsense_request_latency_seconds_bucket` → show latency distribution
4. Query `spendsense_test_f1_macro` → show model quality metric pushed from training

> **Note:** Pushgateway metrics (`spendsense_test_f1_macro`, `spendsense_training_val_f1`,
> `spendsense_pipeline_*`, `spendsense_ui_*`) only populate after a full pipeline run with
> Docker services up. If these metrics show "No data" in Grafana during the demo, trigger
> a few predictions from the Streamlit UI (populates `spendsense_ui_*`) and note that
> training/evaluation metrics populate automatically on each `dvc repro` CI run.

**Grafana (localhost:3001)**

**Credentials:** admin / admin

1. Open `http://localhost:3001`
2. Go to **Dashboards → SpendSense → SpendSense — MLOps Dashboard**
3. Walk through panels:
   - **Request Rate** — requests/sec over time
   - **P95 Latency** — 95th percentile prediction latency
   - **Error Rate** — gauge showing % failed requests
   - **Predictions by Category** — bar chart of which categories are being predicted

Generate some traffic to make the dashboard live:

```bash
# Fire 20 predictions to populate the dashboard
for desc in "Zomato delivery" "Uber ride" "Netflix" "Apollo pharmacy" "BESCOM bill" \
            "Amazon order" "SIP investment" "Tax payment" "Salary credit" "NGO donation" \
            "Swiggy food" "Ola cab" "Spotify premium" "BookMyShow" "Flipkart purchase" \
            "Lab test" "Credit card payment" "Passport fees" "Temple donation" "Freelance payment"; do
  curl -s -X POST http://localhost:8000/predict \
    -H "Content-Type: application/json" \
    -d "{\"description\": \"$desc\"}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['description'],'→',d['predicted_category'])"
done
```

Then refresh Grafana — all panels will update.

---

## Step 7 — Show End-to-End Data Flow (Narrative)

Use this talking point to tie it all together:

```
Raw CSV (data/raw/)
      ↓ Airflow DAG validates schema, checks nulls, detects drift
      ↓ src/data/ingest.py  →  data/ingested/
      ↓ src/data/preprocess.py  →  data/processed/ (vocab, splits)
      ↓ src/models/train.py  →  models/latest_model.pt + MLflow run
      ↓ src/models/evaluate.py  →  metrics/eval_metrics.json (F1 ≥ 0.70 gate)
      ↓ FastAPI loads model on startup
      ↓ Streamlit calls FastAPI /predict
      ↓ Prometheus scrapes /metrics → Grafana dashboard
      ↓ GitHub Actions CI/CD orchestrates the whole pipeline on every push
```

---

## Stopping Services

```bash
docker compose down          # stop containers, keep volumes (MLflow history preserved)
docker compose down -v       # stop + wipe volumes (resets Grafana, Prometheus, Airflow DB)
```

Use `docker compose down` (without `-v`) to preserve all state for the next demo session.

---

## Persistence Notes

| Artifact | Where stored | Survives `docker compose down`? |
|---|---|---|
| Trained model | `models/latest_model.pt` (local file) | ✅ Yes |
| Processed data | `data/processed/` (local files) | ✅ Yes |
| MLflow runs | `mlruns/mlflow.db` (local file, mounted) | ✅ Yes |
| Grafana dashboards | `grafana_data` (named Docker volume) | ✅ Yes (without `-v`) |
| Prometheus data | `prometheus_data` (named Docker volume) | ✅ Yes (without `-v`) |
| Airflow DB | `airflow_db` (named Docker volume) | ✅ Yes (without `-v`) |
