# SpendSense — Services & Ports

| # | Service | Container Name | URL | Purpose |
|---|---|---|---|---|
| 1 | **MLflow** | `spendsense_mlflow` | http://localhost:5000 | Experiment tracking + model registry |
| 2 | **FastAPI Backend** | `spendsense_backend` | http://localhost:8000/docs | REST API for inference |
| 3 | **Streamlit Frontend** | `spendsense_frontend` | http://localhost:8501 | Web UI for predictions |
| 4 | **Apache Airflow** | `spendsense_airflow` | http://localhost:8080 | Data ingestion DAG orchestration |
| 5 | **Prometheus** | `spendsense_prometheus` | http://localhost:9090 | Metrics collection + alert evaluation |
| 6 | **Grafana** | `spendsense_grafana` | http://localhost:3001 | NRT dashboards |
| 7 | **Alertmanager** | `spendsense_alertmanager` | http://localhost:9093 | Alert routing (email via Gmail SMTP) |
| 8 | **Pushgateway** | `spendsense_pushgateway` | http://localhost:9091 | Receives batch job metrics from train/evaluate/Airflow |

Start all services:

```bash
docker compose up -d
```
