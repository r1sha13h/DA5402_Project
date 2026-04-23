#!/bin/bash
set -e
# Grant write access on bind-mounted host directories to the airflow user (uid 50000).
# These dirs are owned by the host user (uid 1000) with mode 775, so "other" gets no
# write — causing PermissionError when ingest writes to data/ingested/.
chmod -R o+w /opt/airflow/project/data /opt/airflow/project/models 2>/dev/null || true
# Drop from root to the airflow user and exec the provided command.
exec su -s /bin/bash airflow "$@"
