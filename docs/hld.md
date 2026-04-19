# High-Level Design (HLD) — SpendSense

## 1. Problem Statement

Bank statements contain raw, unstructured transaction descriptions. Manually categorising them is tedious and error-prone. SpendSense solves this with an automated neural-network-based classifier.

## 2. System Goals

- **ML Goal:** ≥ 85% macro F1-score on held-out test set
- **Latency Goal:** < 200ms inference latency per request
- **Availability:** Service returns 200 on `/health` at all times
- **Observability:** All requests tracked via Prometheus; alerts on > 5% error rate

## 3. High-Level Component Breakdown

```
User
 │
 ▼
Streamlit Frontend (port 8501)
 │  REST API calls
 ▼
FastAPI Backend (port 8000)
 │  loads artefacts from disk
 ▼
BiLSTM Model + Vocab + LabelEncoder
 │
 ├── Prometheus /metrics → Prometheus (9090) → Grafana (3000)
 ├── MLflow tracking → MLflow server (5000)
 └── Data pipeline ← Airflow (8080) + DVC + GitHub Actions
```

## 4. Data Flow

1. **Ingestion:** Raw CSV → Airflow DAG validates schema/nulls/drift → `data/ingested/`
2. **Preprocessing:** `data/ingested/` → tokenise, build vocab, split → `data/processed/`
3. **Training:** `data/processed/` → BiLSTM trains, logs to MLflow → `models/best_model.pt`
4. **Evaluation:** Test split + model → accuracy/F1 computed → `metrics/eval_metrics.json`
5. **Serving:** FastAPI loads model/vocab/label_encoder → serves predictions via REST API
6. **Monitoring:** FastAPI emits Prometheus metrics → Grafana visualises in NRT

## 5. ML Model

- **Architecture:** Bidirectional LSTM (2 layers, 256 hidden dim per direction)
- **Input:** Padded word-index sequence (length 50)
- **Output:** Softmax over 10 expense categories
- **Training data:** ~1.4M real labelled transactions from HuggingFace (10 categories)
- **Performance target:** macro F1 ≥ 0.70 (enforced in CI pipeline)

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
git push → GitHub Actions
    ├── Job 1: lint + pytest (all branches)
    ├── Job 2: dvc repro (main branch only)
    │         └── fail if test F1 < 0.70
    └── Job 3: docker build + smoke tests (main branch only)
```

## 8. Deployment Strategy

- **Local on-prem:** All services in docker-compose on developer's machine
- **No cloud:** Compliant with project guidelines
- **Rollback:** `git checkout <prev-commit>` + `dvc checkout` + `docker compose up`

## 9. Security Considerations

- All inter-service communication is within Docker bridge network
- CORS is configured to allow frontend → backend communication
- No sensitive data — public HuggingFace dataset only
- Grafana and Airflow web UIs protected by username/password (admin/admin for dev)
