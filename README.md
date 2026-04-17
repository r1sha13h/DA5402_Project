# SpendSense — Personal Expense Category Classifier

> **DA5402 MLOps Project** | Bidirectional LSTM + Full MLOps Stack

SpendSense automatically classifies bank transaction descriptions (e.g. *"Zomato payment ₹350"* → **Food & Dining**) using a Bidirectional LSTM neural network, exposed as a REST API and served through an interactive web application.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│              GitHub Actions  (CI/CD Orchestration Layer)             │
│  on: push / PR / schedule  ← self-hosted runner (no cloud)          │
│  jobs: lint → test → dvc repro → validate metrics → docker build    │
└───────────────┬──────────────────────────┬───────────────────────────┘
                │                          │
                ▼                          ▼
┌──────────────────────────┐   ┌───────────────────────────────────────┐
│  Airflow (Data Layer)    │   │  DVC Pipeline (ML Reproducibility)    │
│  DAG: ingestion_pipeline │   │  generate→ingest→preprocess           │
│  - schema validation     │   │           →train→evaluate             │
│  - null checks           │   │  params.yaml drives all stages        │
│  - drift detection       │   │  Git + DVC track data & model         │
└──────────────────────────┘   └──────────────┬────────────────────────┘
                                              ▼
                               ┌──────────────────────────┐
                               │  MLflow Tracking Server  │
                               │  metrics, params, artefacts           │
                               │  Model Registry (→Production)        │
                               └──────────────┬───────────┘
                ┌─────────────────────────────▼─────────────────────────┐
                │             docker-compose (Runtime Layer)            │
                │  FastAPI Backend (/predict /health /ready /metrics)   │
                │  Streamlit Frontend (3 pages)                         │
                │  Prometheus + Grafana (NRT monitoring, >5% alert)     │
                └───────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Concern | Tool |
|---|---|
| CI/CD Orchestrator | **GitHub Actions** (self-hosted runner) |
| Data Engineering | **Apache Airflow** 2.9 |
| ML Pipeline | **DVC** ≥3.50 |
| Experiment Tracking | **MLflow** ≥2.15 |
| Model | **BiLSTM** (PyTorch ≥2.5) |
| Model Serving | **FastAPI** + Uvicorn |
| Frontend | **Streamlit** ≥1.35 |
| Containerisation | **Docker** + **docker-compose** |
| Env Management | **Micromamba** (replaces Miniconda) |
| Monitoring | **Prometheus** 2.52 + **Grafana** 10.4 |
| Version Control | **Git** + **DVC** |

---

## Project Structure

```
DA5402_Project/
├── .github/workflows/ci.yml        # GitHub Actions — outer CI/CD orchestrator
├── airflow/dags/ingestion_dag.py   # Airflow DAG — data ingestion & drift detection
├── backend/app/
│   ├── main.py                     # FastAPI app (predict, health, ready, metrics)
│   ├── predictor.py                # Model loading + inference
│   ├── schemas.py                  # Pydantic I/O schemas
│   └── monitoring.py               # Prometheus metrics
├── frontend/
│   ├── Home.py                     # Single prediction page
│   └── pages/
│       ├── 1_Batch_Predict.py      # CSV / paste batch prediction
│       └── 2_Pipeline_Status.py    # Service health + live metrics
├── src/
│   ├── data/
│   │   ├── generate_synthetic.py   # Synthetic data generator
│   │   ├── ingest.py               # DVC stage: ingest + validate
│   │   └── preprocess.py           # DVC stage: tokenise + split
│   └── models/
│       ├── model.py                # BiLSTMClassifier definition
│       ├── train.py                # DVC stage: train + MLflow logging
│       └── evaluate.py             # DVC stage: evaluate on test set
├── monitoring/
│   ├── prometheus.yml              # Prometheus scrape config
│   └── grafana/provisioning/       # Auto-provisioned Grafana dashboard
├── tests/                          # Pytest unit tests (28 test cases)
├── docs/                           # Architecture, HLD, LLD, test plan, user manual
├── dvc.yaml                        # DVC pipeline definition
├── params.yaml                     # All hyperparameters (single source of truth)
├── MLproject                       # MLflow project entry points
├── conda.yaml                      # MLflow conda environment
└── docker-compose.yml              # 6-service runtime stack
```

---

## Prerequisites

- Python 3.10+
- Docker + Docker Compose v2
- Git
- [Micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html) (replaces Miniconda/conda — ~10 MB binary, fully conda-compatible)
- (Optional) GitHub self-hosted runner for full CI/CD

**Install micromamba (one-time):**
```bash
curl -Ls https://micro.mamba.pm/install.sh | bash
```

---

## End-to-End Setup

### 1 — Clone, create virtual environment, and install dependencies

```bash
git clone <your-repo-url>
cd DA5402_Project

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate    # Linux/macOS
# venv\Scripts\activate     # Windows

# (Recommended) Install CPU-only PyTorch first for faster setup (~200 MB vs ~2 GB)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install all remaining dependencies
pip install -r requirements.txt
```

### 2 — Initialise DVC

Skip this step if `.dvc/` already exists in the repo.

```bash
dvc init
git add .dvc .dvcignore
git commit -m "init dvc"
```

### 3 — Run the full ML pipeline

This runs all 5 stages: generate data → ingest → preprocess → train → evaluate.

```bash
dvc repro
```

Expected output artefacts:
- `data/raw/transactions.csv` — 6,000 synthetic transactions
- `data/processed/` — tokenised arrays, vocab, label encoder
- `models/best_model.pt` — best BiLSTM checkpoint
- `metrics/eval_metrics.json` — test accuracy + F1

Check metrics:
```bash
dvc metrics show
```

### 4 — Start all services with Docker Compose

```bash
docker compose up --build -d
```

> **Note:** The first build downloads Docker images and installs dependencies
> (including PyTorch). This can take **5–15 minutes** depending on your
> internet speed. Subsequent builds use cached layers and are much faster.

Services started:

| Service | URL | Credentials |
|---|---|---|
| Streamlit Frontend | http://localhost:8501 | — |
| FastAPI Backend | http://localhost:8000/docs | — |
| MLflow Tracking UI | http://localhost:5000 | — |
| Apache Airflow UI | http://localhost:8080 | admin / admin |
| Prometheus | http://localhost:9090 | — |
| Grafana Dashboard | http://localhost:3001 | admin / admin |

### 5 — Verify the backend

```bash
# Liveness
curl http://localhost:8000/health

# Single prediction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"description": "Zomato food delivery payment"}'

# Prometheus metrics
curl http://localhost:8000/metrics
```

### 6 — Trigger the Airflow DAG manually

1. Open http://localhost:8080
2. Login: `admin` / `admin`
3. Find `spendsense_ingestion_pipeline`
4. Click ▶ to trigger a manual run
5. Watch all 6 tasks: generate_data → validate_schema → check_nulls → check_drift → run_ingest → trigger_dvc

### 7 — View the Grafana Dashboard

1. Open http://localhost:3001
2. Login: `admin` / `admin`
3. Navigate to **Dashboards → SpendSense → SpendSense — MLOps Dashboard**
4. The dashboard shows: request rate, P95 latency, error rate gauge, predictions by category

---

## Running Tests

```bash
# All unit tests
pytest tests/ -v

# With coverage report
pytest tests/ -v --cov=src --cov=backend --cov-report=term-missing

# Single test file
pytest tests/test_api.py -v
```

---

## GitHub Actions CI/CD

The workflow at `.github/workflows/ci.yml` is the **top-level orchestrator** that coordinates all other tools.

**Jobs:**

| Job | Trigger | What it does |
|---|---|---|
| `test` | All pushes + PRs | Lint (flake8) + pytest |
| `ml-pipeline` | Push to `main` only | `dvc repro` + metric validation (F1 ≥ 0.70) |
| `docker` | Push to `main` only | Docker build + smoke tests on all endpoints |

**Setup a self-hosted runner** (required, no cloud):

```bash
# On your local machine:
# 1. Go to GitHub repo → Settings → Actions → Runners → New self-hosted runner
# 2. Follow the instructions to download and configure the runner
# 3. Start it:
./run.sh
```

Once the runner is active, every `git push` to `main` will trigger the full pipeline.

---

## MLflow Experiment Tracking

Experiments are tracked at `http://localhost:5000`.

**Parameters logged per run:**
- `embed_dim`, `hidden_dim`, `num_layers`, `dropout`
- `batch_size`, `learning_rate`, `epochs`
- `vocab_size`, `num_classes`, `seed`

**Metrics logged per epoch:**
- `train_loss`, `train_acc`, `train_f1_macro`
- `val_loss`, `val_acc`, `val_f1_macro`
- `best_val_f1_macro` (final)

**Artefacts:** model checkpoint, `vocab.pkl`, `label_encoder.pkl`, `params.yaml`

**Re-run with different hyperparameters:**
```bash
# Uses python_env.yaml (virtualenv-based, no conda required)
mlflow run . -P embed_dim=256 -P hidden_dim=512 -P learning_rate=0.0005
```

---

## DVC Pipeline

The `dvc.yaml` defines 5 reproducible stages:

```
generate → ingest → preprocess → train → evaluate
```

Run individual stages:
```bash
dvc repro generate   # Only regenerate data
dvc repro preprocess # Only rerun preprocessing
dvc repro train      # Only retrain
dvc repro            # Full pipeline (incremental)
```

---

## Expense Categories (10 classes)

| Category | Examples |
|---|---|
| Food & Dining | Zomato, Swiggy, restaurant bill |
| Transport | Uber, Ola, petrol pump, metro |
| Utilities | BESCOM bill, Jio recharge, LPG |
| Entertainment | Netflix, BookMyShow, Spotify |
| Shopping | Amazon, Flipkart, Myntra |
| Healthcare | Apollo pharmacy, lab tests |
| Education | Coursera, college fees |
| Travel | MakeMyTrip, hotel booking |
| Housing | Rent, society maintenance |
| Finance | Credit card payment, SIP, LIC |

---

## Documentation

| Document | Location |
|---|---|
| Architecture Diagram | `docs/architecture.md` |
| High-Level Design | `docs/hld.md` |
| Low-Level Design (API specs) | `docs/lld.md` |
| Test Plan + Test Cases | `docs/test_plan.md` |
| User Manual | `docs/user_manual.md` |

---

## Stopping All Services

```bash
docker compose down          # Stop and remove containers
docker compose down -v       # Also remove volumes (wipes MLflow DB, Grafana data)
```