# High-Level Design (HLD) — SpendSense

## 1. Problem Statement

Bank statements contain raw, unstructured transaction descriptions. Manually categorising them is tedious and error-prone. SpendSense solves this with an automated neural-network-based classifier that categorises descriptions in real time with > 98% accuracy.

## 2. System Goals

- **ML Goal:** ≥ 85% macro F1-score on held-out test set (achieved: 98.72%)
- **Latency Goal:** < 200ms inference latency per request
- **Availability:** Service returns 200 on `/health` at all times
- **Observability:** All requests tracked via Prometheus; alerts on > 5% error rate and data drift

## 3. High-Level Component Breakdown

```
User
 │
 ▼
Streamlit Frontend (port 8501)
 │  REST API calls via BACKEND_URL
 ▼
FastAPI Backend (port 8000)
 │  loads artefacts from disk on startup
 ▼
BiLSTM Model + Vocab + LabelEncoder
 │
 ├── Prometheus /metrics → Prometheus (9090) → Grafana (3001)
 ├── Pushgateway (9091) ← training, evaluation, Airflow, Streamlit
 ├── Alertmanager (9093) → email alerts
 ├── MLflow tracking → MLflow server (5000)
 └── Data pipeline ← Airflow (8080) + DVC + GitHub Actions
```

## 4. Data Flow

1. **Ingestion (Airflow):** Loads raw transaction CSV, validates for missing/malformed data, checks if transaction patterns have shifted, merges new data with user corrections, saves clean data ready for training.
2. **Preprocessing (DVC):** Converts transaction text into numbers (tokenization), builds a word dictionary (top 10K words), pads all sequences to length 50, splits data into train/validation/test sets (70/15/15), saves processed arrays and vocabulary.
3. **Training (DVC):** Trains the BiLSTM neural network on the processed data (or fine-tunes from a previous model checkpoint), logs all hyperparameters and metrics to MLflow, automatically registers the best model as ready for production.
4. **Evaluation (DVC):** Tests the trained model on held-out data, calculates accuracy and F1 score per category, fails the pipeline if F1 < 70% (quality gate), saves detailed metrics and confusion matrix.
5. **Serving:** Backend loads the trained model on startup, compresses it using INT8 quantization for ~4× memory savings, serves predictions through REST API endpoints (predict, batch-predict, feedback, drift check).
6. **Feedback Loop:** Users submit corrections via `/feedback` API → feedback collected in `feedback.jsonl` → system detects if user feedback shows >10 percentage-point shift in category distribution → if shift detected, automatically triggers retraining on combined original + feedback data.
7. **Monitoring:** All components (backend, training, evaluation, Airflow, Streamlit) report metrics (request count, latency, error rate, model status, drift flag) → Prometheus collects metrics every 10s → Grafana displays live dashboard → Alertmanager sends email on anomalies.

## 5. ML Model

- **Architecture:** Bidirectional LSTM (2 layers, 256 hidden dim per direction, bidirectional → 512 effective)
- **Input:** Padded word-index sequence (length 50, vocab size 10,002)
- **Embedding:** 128-dim learned embeddings, PAD index zeroed
- **Output:** Softmax over 10 expense categories
- **Training data:** 4.5M raw transactions from HuggingFace `nickmuchi/financial-classification`; ~1.34M rows remain after dropping nulls, unknown categories, and duplicates
- **Run 1:** Full training from scratch on 90% of the cleaned corpus (~1.2M rows), logged as `bilstm_training`
- **Run 2:** The remaining 10% (~134K rows) is a held-out batch that simulates newly arrived data. Airflow checks it for drift, merges it with the 90% training set + user feedback, then DVC fine-tunes for 1 epoch from the Run-1 checkpoint, logged as `bilstm_finetune`
- **Performance:** test macro F1 = 98.72%, test accuracy = 98.75%
- **Inference optimisation:** Dynamic INT8 quantization applied to LSTM and Linear layers at load time on CPU (~4× memory reduction)

## 6. Expense Categories (10 classes)

| Category | Examples |
|---|---|
| Food & Dining | Zomato, Swiggy, restaurant bill |
| Transportation | Uber, Ola, petrol pump |
| Utilities & Services | BESCOM bill, Jio recharge, internet |
| Entertainment & Recreation | Netflix, BookMyShow, gaming |
| Shopping & Retail | Amazon, Flipkart, Myntra |
| Healthcare & Medical | Apollo pharmacy, lab tests |
| Financial Services | Credit card payment, SIP, LIC premium |
| Income | Salary, freelance payment, refund |
| Government & Legal | Tax payment, passport fees, court fees |
| Charity & Donations | NGO donation, temple donation |

## 7. CI/CD Design

```
git push → GitHub Actions (3-job BAT pipeline, ~13 min total)
    ├── Job 1 (~30s): flake8 + pytest (68 tests) + 60% coverage gate
    │   └── runs on every branch push
    ├── Job 2 (~11.5 min): full ML pipeline — main branch only
    │   ├── Create 90-10 drift split
    │   ├── Start services (MLflow, Prometheus, Grafana, Alertmanager, Pushgateway)
    │   ├── DVC Run 1 (ingest → preprocess → train → evaluate on 90% data)
    │   ├── F1 gate: fail if test_f1_macro < 0.70
    │   ├── Trigger Airflow DAG: validates held-out 10% batch, detects drift, merges it with the 90% baseline + user feedback
    │   ├── DVC Run 2 (fine-tune on combined corpus for 1 epoch)
    │   └── Stage scoped artifacts at $HOME/ss-ci-$GITHUB_RUN_ID/ for Job 3
    └── Job 3 (~1 min): smoke tests — main branch only
        ├── Restore artifacts (model, vocab, label_encoder, mlruns.db) from local stage
        ├── Docker build + start backend + frontend
        └── Smoke test all API endpoints (/predict, /health, /models, /metrics, Streamlit)
```

## 8. Deployment Strategy

- **Local on-prem:** All 8 services in docker-compose on developer's machine
- **No cloud:** Compliant with project guidelines
- **Model hot-swap:** `POST /models/switch` loads any MLflow run's model without container restart
- **Rollback:** `git checkout <prev-commit>` + `dvc checkout` + `docker compose up`

## 9. Security Considerations

- All inter-service communication is within Docker bridge network (no external exposure)
- CORS is configured to allow frontend → backend communication
- No sensitive data — public HuggingFace dataset only (no PII)
- Grafana and Airflow web UIs protected by username/password (admin/admin for dev)
- SMTP password for email alerts stored as GitHub Actions secret, injected via env var (never hardcoded)

## 10. Feedback Loop & Drift Detection

Users submit corrections via `POST /feedback`, which appends each entry (description, predicted category, actual category) to `feedback/feedback.jsonl`. The `GET /drift` endpoint reads this log and compares the actual-category distribution against `feature_baseline.json`; it flags drift if any category shifts by more than 10 percentage points. Separately, Airflow's daily `check_drift` task compares the held-out drift file against `baseline_stats.json` from the last ingest run. If either mechanism detects drift, Airflow merges the new data with the training set and triggers DVC retraining automatically.
