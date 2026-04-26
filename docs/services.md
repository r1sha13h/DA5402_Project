# SpendSense — Services & Ports

| # | Service | Container Name | URL | Credentials | Purpose |
|---|---|---|---|---|---|
| 1 | **MLflow** | `spendsense_mlflow` | http://localhost:5000 | — | Experiment tracking + model registry |
| 2 | **FastAPI Backend** | `spendsense_backend` | http://localhost:8000/docs | — | REST API for inference (9 endpoints) |
| 3 | **Streamlit Frontend** | `spendsense_frontend` | http://localhost:8501 | — | Web UI for predictions |
| 4 | **Apache Airflow** | `spendsense_airflow` | http://localhost:8080 | admin / admin | Data ingestion DAG orchestration |
| 5 | **Prometheus** | `spendsense_prometheus` | http://localhost:9090 | — | Metrics collection + alert evaluation |
| 6 | **Grafana** | `spendsense_grafana` | http://localhost:3001 | admin / admin | NRT dashboards (7 panels) |
| 7 | **Alertmanager** | `spendsense_alertmanager` | http://localhost:9093 | — | Alert routing (email via Gmail SMTP) |
| 8 | **Pushgateway** | `spendsense_pushgateway` | http://localhost:9091 | — | Receives batch-job metrics from train/eval/Airflow/Streamlit |

## Start all services

```bash
docker compose up -d
```

## Start only infra services (no app)

```bash
docker compose up -d mlflow alertmanager pushgateway prometheus grafana
```

## Start only app services (requires trained model at models/latest_model.pt)

```bash
docker compose up -d backend frontend
```

## Notes

- Grafana's **internal** Docker port is `3000`; the **host** port is `3001`. Inter-container communication (e.g. Prometheus scraping Grafana) uses `grafana:3000`.
- The backend container reads the model from `./models:/app/models:ro` (bind mount). Ensure `models/latest_model.pt` exists before starting the backend.
- Airflow runs in standalone mode (webserver + scheduler in one process) with a SQLite backend. It is not a production Airflow deployment.
- `feedback/feedback.jsonl` is bind-mounted into the backend container so corrections survive container restarts.
