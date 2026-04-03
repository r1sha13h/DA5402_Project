FROM apache/airflow:2.9.1-python3.10

USER root
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
USER airflow

COPY airflow/requirements.txt /tmp/airflow-requirements.txt
RUN pip install --no-cache-dir -r /tmp/airflow-requirements.txt

COPY airflow/dags/ ${AIRFLOW_HOME}/dags/
