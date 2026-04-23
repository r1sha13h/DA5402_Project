# Statement

Here is a complete breakdown of everything you need to know — the grading rubric, followed by a custom project tailored for you, and finally a formal project statement.

---

## Grading Rubric Breakdown

The project is evaluated across **four major areas** totalling **35 points**.

## Demonstration — 10 pts

| Sub-area | Points | Key Criteria |
| --- | --- | --- |
| Web App UI/UX | 6 | Intuitive UX, non-technical usability, responsiveness, aesthetics, user manual |
| ML Pipeline Visualization | 4 | Pipeline visibility (separate screen or MLOps tool UI), pipeline management console, error/success tracking, throughput |


## Software Engineering — 5 pts

- **Design Principles (2 pts):** Architecture diagram, HLD, LLD with API I/O specs, strict loose coupling between frontend and backend via REST APIs
- **Implementation (2 pts):** PEP8-style Python, logging, exception handling, inline documentation, unit tests
- **Testing (1 pt):** Test plan, enumerated test cases, test report with pass/fail counts, acceptance criteria

## MLOps Implementation — 12 pts

| Component | Points | What's Needed |
| --- | --- | --- |
| Data Engineering | 2 | Airflow or Spark-based ingestion/transformation pipeline |
| Source Control & CI | 2 | DVC DAG, Git + DVC for data/model versioning |
| Experiment Tracking | 2 | MLflow tracking — metrics, params, artifacts (beyond just Autolog) |
| Prometheus + Grafana | 2 | Instrumentation of all components, NRT dashboards, alerting on >5% error rate |
| Software Packaging | 4 | MLflow model APIification, MLprojects, FastAPI backend, Dockerized frontend + backend, docker-compose |

## Viva — 8 pts

Eight 1-point questions covering project explanation, tool knowledge, design choices, problems faced, defending decisions, and live bug fixes.

## Documentation Required

Architecture diagram, HLD, LLD (with API specs), test plan + cases, and a user manual for non-technical users.

---

## Proposed Project: **SpendSense — Personal Expense Category Classifier**

## Why This Project?

This is a **neural network-based text classifier** that automatically categorizes bank transaction descriptions (e.g., *"Zomato payment ₹350"* → `Food & Dining`, *"BESCOM electricity bill"* → `Utilities`). It hits every rubric criterion, has direct daily-life relevance, and the model is a lightweight feedforward/LSTM network that runs comfortably on a CPU-only MacBook.

- **Data acquisition:** Freely available on Kaggle (e.g., "personal finance transaction datasets") or you can generate synthetic data using Python — no scraping, no APIs, no GPU
- **Neural network:** A 1D-CNN or biLSTM over TF-IDF / word-embedding inputs; fast to train (<5 min on CPU)
- **Business relevance:** Finance management apps (Walnut, ET Money) are mainstream; this is a real production ML feature

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│              GitHub Actions  (CI/CD Orchestration Layer)             │
│  on: push / PR / schedule                                            │
│  jobs: lint → test → dvc repro → validate metrics → docker build    │
│         └── triggers Airflow DAG via REST API when needed            │
└───────────────┬──────────────────────────┬───────────────────────────┘
                │                          │
                ▼                          ▼
┌──────────────────────────┐   ┌───────────────────────────────────────┐
│  Airflow (Data Layer)    │   │  DVC Pipeline (ML Reproducibility)    │
│  DAG: ingestion_pipeline │   │  ingest → preprocess → train → eval   │
│  - schema validation     │   │  params.yaml drives all stages        │
│  - null checks           │   │  Git + DVC track data & model         │
│  - raw data → data/raw/  │   └──────────────┬────────────────────────┘
└──────────────────────────┘                  │
                                              ▼
                               ┌──────────────────────────┐
                               │  MLflow Tracking Server  │
                               │  - metrics, params, artefacts
                               │  - Model Registry        │
                               │    (Staging → Production)│
                               └──────────────┬───────────┘
                                              │
                ┌─────────────────────────────▼─────────────────────────┐
                │             docker-compose (Runtime Layer)            │
                │  ┌─────────────────┐  ┌────────────────────────────┐  │
                │  │ FastAPI Backend │  │  Streamlit Frontend        │  │
                │  │ /predict        │←─│  Single & Batch Prediction │  │
                │  │ /health /ready  │  │  Pipeline Status Page      │  │
                │  │ /metrics        │  └────────────────────────────┘  │
                │  └────────┬────────┘                                  │
                │           │                                           │
                │  ┌────────▼────────────────────┐                      │
                │  │ Prometheus + Grafana        │                      │
                │  │ NRT dashboards, alerting    │                      │
                │  │ >5% error rate alert        │                      │
                │  └─────────────────────────────┘                      │
                └───────────────────────────────────────────────────────┘
```

## Technology Stack Mapping

| Guideline Requirement | Tool Used |
| --- | --- |
| Data Engineering | Apache Airflow DAG for CSV ingestion + validation |
| Source Control | Git + DVC (data versioning for CSV versions) |
| Experiment Tracking | MLflow (log: accuracy, F1, loss, vocab size, LR) |
| Model Serving | MLflow model wrapped in FastAPI (`/predict`, `/health`, `/ready`) |
| Containerization | Docker + docker-compose (3 services: frontend, backend, monitoring) |
| Monitoring | Prometheus exporter in FastAPI + Grafana dashboard |
| CI Pipeline | GitHub Actions orchestrating the DVC pipeline DAG (ingest → preprocess → train → evaluate) |

## Why It Fits Your Constraints

- **Low compute:** The biLSTM on ~50k transactions trains in minutes; no GPU needed
- **Moderate complexity:** Involves text preprocessing, sequence modeling, and full MLOps plumbing — non-trivial but tractable
- **Neural network:** biLSTM or 1D-CNN with embedding layer qualifies strongly
- **Easy data:** Public datasets (e.g., "Bank Transaction Dataset") or programmatically generated synthetic data in Python

---

## 📋 Project Statement

> SpendSense: An Intelligent Personal Finance Transaction Classifier with MLOps
> 
> 
> **Problem Statement:**
> 
> Millions of individuals struggle to track and understand their spending patterns because bank statements contain raw, unstructured transaction descriptions that are neither categorized nor actionable. Manually labeling expenses into categories such as *Food*, *Transport*, *Utilities*, or *Entertainment* is tedious and error-prone. There is a clear need for an automated, intelligent system that can classify these transaction descriptions in real time.
> 
> **Application Domain:**
> 
> Personal Finance & FinTech — a high-impact daily-life domain relevant to budgeting apps, banking dashboards, and expense management tools.
> 
> **Objective:**
> 
> To build a neural network-based text classification system (using a bidirectional LSTM or 1D-CNN with word embeddings) that accepts a raw transaction description as input and predicts the correct expense category. The system will be exposed as a REST API and served through an interactive web application accessible to non-technical users.
> 
> **Expected Outcome:**
> 
> A fully functional web application where a user can paste or upload transaction descriptions and receive instant category predictions with confidence scores, targeting ≥85% macro F1-score on a held-out test set and inference latency <200ms per request.
> 
> **MLOps Practices:**
> 
> The entire ML lifecycle will be managed using MLOps best practices: data ingestion and validation will be automated via an **Apache Airflow DAG**; all data and model versions will be tracked using **DVC and Git**; experiments will be logged in **MLflow** (metrics, hyperparameters, artifacts); the model will be served via **FastAPI** packaged with **MLflow Projects**; the application (frontend + backend + monitoring) will be **Dockerized and orchestrated via docker-compose**; and **GitHub Actions** will act as the separate CI/CD orchestration layer, coordinating tests, `dvc repro`, MLflow validation checks, Docker image builds, and compose-based smoke checks across Airflow, DVC, MLflow, and Docker; production health will be monitored in near-real-time using **Prometheus and Grafana** with alerting configured for error rates exceeding 5% and data drift on input token distributions.
>