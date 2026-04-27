# SpendSense — Project Index

> DA5402 MLOps Project

---

## Report

- [report.md](report.md)
- [report.html](report.html)

---

## Docs

- [docs/architecture.md](docs/architecture.md)
- [docs/hld.md](docs/hld.md)
- [docs/lld.md](docs/lld.md)
- [docs/test_plan.md](docs/test_plan.md)
- [docs/user_manual.md](docs/user_manual.md)

---

## CI/CD

- [.github/workflows/ci.yml](.github/workflows/ci.yml)

---

## Pipeline & Config

- [dvc.yaml](dvc.yaml)
- [params.yaml](params.yaml)
- [docker-compose.yml](docker-compose.yml)
- [MLproject](MLproject)
- [conda.yaml](conda.yaml)
- [setup.cfg](setup.cfg)

---

## Source — ML Pipeline

- [src/data/ingest.py](src/data/ingest.py)
- [src/data/preprocess.py](src/data/preprocess.py)
- [src/models/model.py](src/models/model.py)
- [src/models/train.py](src/models/train.py)
- [src/models/evaluate.py](src/models/evaluate.py)

---

## Backend

- [backend/app/main.py](backend/app/main.py)
- [backend/app/predictor.py](backend/app/predictor.py)
- [backend/app/schemas.py](backend/app/schemas.py)
- [backend/app/monitoring.py](backend/app/monitoring.py)
- [backend/Dockerfile](backend/Dockerfile)

---

## Frontend

- [frontend/Home.py](frontend/Home.py)
- [frontend/pages/1_Batch_Predict.py](frontend/pages/1_Batch_Predict.py)
- [frontend/pages/2_Pipeline_Status.py](frontend/pages/2_Pipeline_Status.py)
- [frontend/Dockerfile](frontend/Dockerfile)

---

## Airflow

- [airflow/dags/ingestion_dag.py](airflow/dags/ingestion_dag.py)
- [airflow/Dockerfile](airflow/Dockerfile)

---

## Monitoring

- [monitoring/prometheus.yml](monitoring/prometheus.yml)
- [monitoring/alert_rules.yml](monitoring/alert_rules.yml)
- [monitoring/alertmanager.yml](monitoring/alertmanager.yml)
- [monitoring/alertmanager-entrypoint.sh](monitoring/alertmanager-entrypoint.sh)
- [monitoring/grafana/provisioning/](monitoring/grafana/provisioning/)

---

## Tests

- [tests/test_ingest.py](tests/test_ingest.py)
- [tests/test_preprocess.py](tests/test_preprocess.py)
- [tests/test_model.py](tests/test_model.py)
- [tests/test_api.py](tests/test_api.py)

---

## Images

- [images/](images/)