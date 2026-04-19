"""Apache Airflow DAG — SpendSense data ingestion and validation pipeline.

This DAG runs daily (or on demand) and orchestrates:
    1. verify_raw_data — ensure raw CSV exists in data/raw/
    2. validate_schema — check required columns and types
    3. check_nulls     — detect and report null values
    4. check_drift     — compare distribution to baseline (if baseline exists)
    5. run_ingest      — validate and write ingested CSV
    6. trigger_dvc     — run `dvc repro` to retrain model when data changes

Schedule: @daily  (configurable via AIRFLOW_INGESTION_SCHEDULE env var)
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta

import requests

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/opt/airflow/project")
RAW_PATH = os.path.join(PROJECT_ROOT, "data", "raw", "transactions.csv")
INGESTED_PATH = os.path.join(PROJECT_ROOT, "data", "ingested", "transactions.csv")
BASELINE_PATH = os.path.join(PROJECT_ROOT, "data", "ingested", "baseline_stats.json")

DEFAULT_ARGS = {
    "owner": "spendsense",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "start_date": datetime(2024, 1, 1),
}

SCHEDULE = os.environ.get("AIRFLOW_INGESTION_SCHEDULE", "@daily")


# ── Task callables ────────────────────────────────────────────────────────────

def task_verify_raw_data(**context):
    """Verify that the raw CSV exists in data/raw/."""
    if not os.path.exists(RAW_PATH):
        raise FileNotFoundError(
            f"Raw data not found at {RAW_PATH}. "
            "Please place transactions.csv in data/raw/ before running the pipeline."
        )
    size_mb = os.path.getsize(RAW_PATH) / (1024 * 1024)
    logger.info("Raw data found at %s — %.1f MB.", RAW_PATH, size_mb)
    return {"exists": True, "path": RAW_PATH, "size_mb": round(size_mb, 1)}


def task_validate_schema(**context):
    """Validate that the raw CSV has required columns and correct dtypes.

    Reads only the first 1000 rows for speed on large datasets.
    """
    import pandas as pd  # noqa: PLC0415

    df = pd.read_csv(RAW_PATH, nrows=1000)
    required = {"description", "category"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Schema validation failed — missing columns: {missing}")

    if not all(pd.api.types.is_string_dtype(df[c]) for c in ["description", "category"]):
        raise TypeError("Columns 'description' and 'category' must be string type.")

    logger.info("Schema validation passed. Columns: %s", list(df.columns))
    return {"columns": list(df.columns)}


def task_check_nulls(**context):
    """Check for null values in required columns and report counts."""
    import pandas as pd  # noqa: PLC0415

    df = pd.read_csv(RAW_PATH, usecols=["description", "category"])
    null_counts = df[["description", "category"]].isnull().sum().to_dict()
    total_nulls = sum(null_counts.values())

    if total_nulls > 0:
        logger.warning("Null values detected: %s", null_counts)
    else:
        logger.info("Null check passed — no nulls found.")

    return {"null_counts": null_counts, "total_nulls": int(total_nulls)}


def task_check_drift(**context):
    """Compare current data distribution against saved baseline stats.

    Logs a warning if category distribution shifts by more than 10%.
    """
    import pandas as pd  # noqa: PLC0415

    df = pd.read_csv(RAW_PATH, usecols=["category"])
    current_dist = df["category"].value_counts(normalize=True).to_dict()

    if not os.path.exists(BASELINE_PATH):
        logger.info("No baseline found — skipping drift check (first run).")
        return {"drift_detected": False, "reason": "no baseline"}

    with open(BASELINE_PATH, "r") as fh:
        baseline = json.load(fh)

    baseline_dist = baseline.get("category_distribution", {})
    total_baseline = sum(baseline_dist.values()) or 1
    baseline_norm = {k: v / total_baseline for k, v in baseline_dist.items()}

    drift_flags = {}
    for cat in set(list(current_dist.keys()) + list(baseline_norm.keys())):
        cur = current_dist.get(cat, 0.0)
        base = baseline_norm.get(cat, 0.0)
        shift = abs(cur - base)
        if shift > 0.10:
            drift_flags[cat] = {"baseline": round(base, 4), "current": round(cur, 4),
                                 "shift": round(shift, 4)}

    if drift_flags:
        logger.warning("Data drift detected: %s", drift_flags)
    else:
        logger.info("No significant data drift detected.")

    return {"drift_detected": bool(drift_flags), "drift_details": drift_flags}


def task_run_ingest(**context):
    """Run the DVC ingest stage to validate and write the ingested CSV."""
    result = subprocess.run(
        ["python", "-m", "src.data.ingest"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    logger.info("STDOUT: %s", result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"Ingest script failed:\n{result.stderr}")
    return {"returncode": result.returncode}


def task_trigger_dvc(**context):
    """Trigger the CI/CD pipeline via GitHub Actions when data drift is detected.

    Posts a workflow_dispatch event to GitHub Actions, which runs the full DVC
    pipeline (ingest → preprocess → train → evaluate) in a controlled environment
    with proper MLflow / Prometheus integration. Skips if no drift is detected.

    Requires GITHUB_PAT and GITHUB_REPO environment variables.
    """
    ti = context["ti"]
    drift_result = ti.xcom_pull(task_ids="check_drift")
    drift_detected = drift_result.get("drift_detected", False) if drift_result else False

    if not drift_detected:
        logger.info("No drift detected — skipping GitHub Actions trigger.")
        return {"skipped": True}

    github_pat = os.environ.get("GITHUB_PAT", "")
    github_repo = os.environ.get("GITHUB_REPO", "r1sha13h/DA5402_Project")

    if not github_pat:
        logger.warning("GITHUB_PAT not set — cannot trigger GitHub Actions workflow.")
        return {"skipped": True, "reason": "GITHUB_PAT not configured"}

    api_url = f"https://api.github.com/repos/{github_repo}/actions/workflows/ci.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "ref": "main",
        "inputs": {
            "run_full_pipeline": "true",
        },
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        if response.status_code == 204:
            logger.info("GitHub Actions workflow dispatched successfully.")
            return {"triggered": True, "status_code": 204}
        else:
            logger.warning(
                "GitHub Actions dispatch returned HTTP %d: %s",
                response.status_code, response.text[:500],
            )
            return {"triggered": False, "status_code": response.status_code}
    except requests.RequestException as exc:
        logger.error("Failed to trigger GitHub Actions: %s", exc)
        raise RuntimeError(f"GitHub Actions dispatch failed: {exc}") from exc


# ── DAG definition ────────────────────────────────────────────────────────────

with DAG(
    dag_id="spendsense_ingestion_pipeline",
    default_args=DEFAULT_ARGS,
    description="SpendSense data ingestion, validation, and drift detection",
    schedule_interval=SCHEDULE,
    catchup=False,
    tags=["spendsense", "data-engineering", "mlops"],
) as dag:

    verify_raw_data = PythonOperator(
        task_id="verify_raw_data",
        python_callable=task_verify_raw_data,
    )

    validate_schema = PythonOperator(
        task_id="validate_schema",
        python_callable=task_validate_schema,
    )

    check_nulls = PythonOperator(
        task_id="check_nulls",
        python_callable=task_check_nulls,
    )

    check_drift = PythonOperator(
        task_id="check_drift",
        python_callable=task_check_drift,
    )

    run_ingest = PythonOperator(
        task_id="run_ingest",
        python_callable=task_run_ingest,
    )

    trigger_dvc = PythonOperator(
        task_id="trigger_dvc",
        python_callable=task_trigger_dvc,
    )

    # Pipeline dependency chain
    verify_raw_data >> validate_schema >> check_nulls >> check_drift >> run_ingest >> trigger_dvc
