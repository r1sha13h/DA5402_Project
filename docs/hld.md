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

1. **Ingestion (Airflow):** Raw CSV → 9-task DAG validates schema/nulls, detects drift, optionally merges drift file + feedback corrections → `data/raw/transactions.csv`
2. **Preprocessing (DVC):** `data/raw/` → tokenise, build vocab (top-10K, min_freq=2), pad/truncate to 50 tokens, stratified 70/15/15 split → `data/processed/` numpy arrays + `vocab.pkl` + `label_encoder.pkl` + `feature_baseline.json`
3. **Training (DVC):** `data/processed/` → BiLSTM trains (or fine-tunes from prior checkpoint), logs to MLflow, auto-promotes to `Staging` → `models/latest_model.pt`
4. **Evaluation (DVC):** Test split + model → accuracy/F1/confusion matrix → `metrics/eval_metrics.json`; exits non-zero if F1 < 0.70 (CI gate)
5. **Serving:** FastAPI loads model/vocab/label_encoder at startup, applies dynamic INT8 quantization → serves predictions via REST API
6. **Feedback loop:** `POST /feedback` appends ground-truth labels to `feedback/feedback.jsonl`; `GET /drift` compares feedback distribution to `feature_baseline.json`, flags > 10pp shifts; Airflow `check_drift` task detects shifts > 10pp in held-out data and triggers retraining
7. **Monitoring:** FastAPI exposes `/metrics` (pull); training, evaluation, Airflow, Streamlit push to Pushgateway → Prometheus → Grafana NRT dashboard

## 5. ML Model

- **Architecture:** Bidirectional LSTM (2 layers, 256 hidden dim per direction, bidirectional → 512 effective)
- **Input:** Padded word-index sequence (length 50, vocab size 10,002)
- **Embedding:** 128-dim learned embeddings, PAD index zeroed
- **Output:** Softmax over 10 expense categories
- **Training data:** 4.5M real labelled transactions from HuggingFace `nickmuchi/financial-classification`
- **Run 1:** Full training from scratch on 90% baseline corpus (~1.2M rows), logged as `bilstm_training`
- **Run 2:** 1-epoch fine-tuning from Run-1 checkpoint on combined 90%+10%+feedback corpus, logged as `bilstm_finetune`
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
    ├── Job 1 (~40s): flake8 + pytest (68 tests) + 60% coverage gate
    │   └── runs on every branch push
    ├── Job 2 (~11 min): full ML pipeline — main branch only
    │   ├── Create 90-10 drift split
    │   ├── Start infra (MLflow, Prometheus, Grafana, Alertmanager, Pushgateway)
    │   ├── DVC Run 1 (ingest → preprocess → train → evaluate on 90% data)
    │   ├── F1 gate: fail if test_f1_macro < 0.70
    │   ├── Start Airflow + trigger spendsense_ingestion_pipeline DAG
    │   ├── DVC Run 2 (fine-tune on 90%+10%+feedback for 1 epoch)
    │   └── Upload scoped artifacts for Job 3
    └── Job 3 (~1.5 min): smoke tests — main branch only
        ├── Download artifacts (model, vocab, label_encoder, mlruns.db)
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

```
POST /feedback (description, predicted, actual)
    → feedback/feedback.jsonl (appended)
    → GET /drift: reads feedback.jsonl, computes actual_category distribution
                  vs feature_baseline.json; flags > 10pp per-category shift
    → Airflow check_drift (daily): compares transactions_drift.csv
                                   vs baseline_stats.json from last ingest
    → if drift detected → combine_data → trigger_dvc → DVC retraining
```
