FROM apache/airflow:2.9.1-python3.10

USER root
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
USER airflow

COPY airflow/requirements.txt /tmp/airflow-requirements.txt
RUN pip install --no-cache-dir -r /tmp/airflow-requirements.txt

COPY airflow/dags/ ${AIRFLOW_HOME}/dags/

# Switch back to root so the entrypoint can chmod the bind-mounted data dirs
# before dropping to the airflow user (uid 50000) at runtime.
USER root
COPY airflow/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
