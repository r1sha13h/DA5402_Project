"""SpendSense ingestion and validation pipeline.

Flow: verify → validate → nulls → drift → branch (retrain if needed)
"""

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta

import requests

try:
    from prometheus_client import CollectorRegistry, Gauge, pushadd_to_gateway
    _PUSHGATEWAY_AVAILABLE = True
except ImportError:
    _PUSHGATEWAY_AVAILABLE = False

PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "http://pushgateway:9091")

from airflow import DAG
from airflow.operators.python import BranchPythonOperator, PythonOperator

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/opt/airflow/project")
RAW_PATH     = os.path.join(PROJECT_ROOT, "data", "raw",      "transactions.csv")
RAW_90_PATH  = os.path.join(PROJECT_ROOT, "data", "raw",      "transactions_90.csv")
DRIFT_POLL_PATH = os.path.join(PROJECT_ROOT, "data", "drift", "transactions_drift.csv")
INGESTED_PATH   = os.path.join(PROJECT_ROOT, "data", "ingested", "transactions.csv")
BASELINE_PATH   = os.path.join(PROJECT_ROOT, "data", "ingested", "baseline_stats.json")
FEEDBACK_LOG    = os.path.join(PROJECT_ROOT, "feedback", "feedback.jsonl")

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


def _push_pipeline_metrics(**metrics: float) -> None:
    """Send metrics to Pushgateway. Uses pushadd to keep existing metrics."""
    if not _PUSHGATEWAY_AVAILABLE:
        return
    try:
        registry = CollectorRegistry()
        for name, value in metrics.items():
            Gauge(f"spendsense_{name}", f"SpendSense pipeline metric: {name}",
                  registry=registry).set(value)
        pushadd_to_gateway(PUSHGATEWAY_URL, job="spendsense_pipeline", registry=registry)
    except Exception as exc:
        logger.warning("Could not push pipeline metrics: %s", exc)


# Tasks

def task_verify_raw_data(**context):
    path = DRIFT_POLL_PATH if os.path.exists(DRIFT_POLL_PATH) else RAW_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Expected data at {DRIFT_POLL_PATH} (drift) or {RAW_PATH} (raw). "
            "Place transactions.csv in data/raw/ before running the pipeline."
        )
    size_mb = os.path.getsize(path) / (1024 * 1024)
    logger.info("Data found at %s — %.1f MB.", path, size_mb)
    return {"exists": True, "path": path, "size_mb": round(size_mb, 1)}


def task_validate_schema(**context):
    import pandas as pd  # noqa: PLC0415

    path = DRIFT_POLL_PATH if os.path.exists(DRIFT_POLL_PATH) else RAW_PATH
    df = pd.read_csv(path, nrows=1000)
    required = {"description", "category"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Schema validation failed — missing columns: {missing}")
    logger.info("Schema validation passed. Columns: %s", list(df.columns))
    return {"columns": list(df.columns)}


def task_check_nulls(**context):
    import pandas as pd  # noqa: PLC0415

    path = DRIFT_POLL_PATH if os.path.exists(DRIFT_POLL_PATH) else RAW_PATH
    df = pd.read_csv(path, usecols=["description", "category"])
    null_counts = df.isnull().sum().to_dict()
    total_nulls = sum(null_counts.values())
    if total_nulls > 0:
        logger.warning("Null values detected: %s", null_counts)
    return {"null_counts": null_counts, "total_nulls": int(total_nulls)}


def task_check_drift(**context):
    """Check for shift between 10% drift file and 90% baseline."""
    import pandas as pd  # noqa: PLC0415

    if not os.path.exists(DRIFT_POLL_PATH):
        logger.info("No drift file at %s — skipping drift check.", DRIFT_POLL_PATH)
        return {"drift_detected": False, "reason": "no_drift_file"}

    df = pd.read_csv(DRIFT_POLL_PATH, usecols=["category"])
    current_dist = df["category"].value_counts(normalize=True).to_dict()

    if not os.path.exists(BASELINE_PATH):
        logger.info("No baseline found at %s — skipping drift check.", BASELINE_PATH)
        return {"drift_detected": False, "reason": "no_baseline"}

    with open(BASELINE_PATH) as fh:
        baseline = json.load(fh)

    # Compare category proportions (baseline has raw counts)
    baseline_dist = baseline.get("category_distribution", {})
    total_baseline = sum(baseline_dist.values()) or 1
    baseline_norm = {k: v / total_baseline for k, v in baseline_dist.items()}

    drift_flags = {}
    # Track categories with >10% shift
    for cat in set(list(current_dist) + list(baseline_norm)):
        cur  = current_dist.get(cat, 0.0)
        base = baseline_norm.get(cat, 0.0)
        shift = abs(cur - base)
        if shift > 0.10:
            drift_flags[cat] = {
                "baseline": round(base, 4),
                "current":  round(cur, 4),
                "shift":    round(shift, 4),
            }

    drift_detected = bool(drift_flags)
    logger.info(
        "Drift check: %s | flags=%s",
        "DETECTED" if drift_detected else "clean",
        drift_flags,
    )
    _push_pipeline_metrics(pipeline_drift_detected=float(drift_detected))
    return {"drift_detected": drift_detected, "drift_details": drift_flags}


def task_route_on_drift(**context):
    """Branch to combine_data if drift found, else finish."""
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="check_drift")
    if result and result.get("drift_detected"):
        logger.info("Drift detected → routing to combine_data.")
        return "combine_data"
    logger.info("No drift → routing directly to pipeline_complete.")
    return "pipeline_complete"


def task_combine_data(**context):
    """Merge 90% baseline, 10% drift, and feedback into transactions.csv."""
    import pandas as pd  # noqa: PLC0415

    dfs = []

    if os.path.exists(RAW_90_PATH):
        df_90 = pd.read_csv(RAW_90_PATH)
        dfs.append(df_90)
        logger.info("Loaded 90%% baseline: %d rows", len(df_90))
    else:
        logger.warning("90%% baseline not found at %s", RAW_90_PATH)

    if os.path.exists(DRIFT_POLL_PATH):
        df_drift = pd.read_csv(DRIFT_POLL_PATH)
        dfs.append(df_drift)
        logger.info("Loaded drift data: %d rows", len(df_drift))

    if os.path.exists(FEEDBACK_LOG):
        feedback_rows = []
        with open(FEEDBACK_LOG) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    continue
                desc = entry.get("description", "").strip()
                actual = entry.get("actual_category", "").strip()
                if desc and actual:
                    feedback_rows.append({"description": desc, "category": actual})
        if feedback_rows:
            df_fb = pd.DataFrame(feedback_rows)
            dfs.append(df_fb)
            logger.info("Loaded %d feedback corrections", len(df_fb))

    if not dfs:
        raise RuntimeError("No data sources found for combine_data.")

    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["description", "category"])
    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)
    combined.to_csv(RAW_PATH, index=False)
    logger.info("Combined dataset written: %d rows → %s", len(combined), RAW_PATH)
    return {"rows": len(combined)}


def task_run_ingest(**context):
    # DVC Run 2 handles ingest in CI
    if os.environ.get("GITHUB_ACTIONS") == "true":
        logger.info("CI mode: skipping run_ingest — DVC pipeline will re-run ingest after combine_data.")
        _push_pipeline_metrics(pipeline_ingest_success=1.0)
        return {"skipped": True, "reason": "ci_mode"}
    # Clear ingested dir to force fresh output (avoid ownership issues on bind mounts)
    ingested_dir = os.path.dirname(INGESTED_PATH)
    if os.path.isdir(ingested_dir):
        try:
            shutil.rmtree(ingested_dir)
        except OSError as exc:
            logger.warning("Could not clear %s: %s — subprocess will attempt overwrite", ingested_dir, exc)
    os.makedirs(ingested_dir, exist_ok=True)
    result = subprocess.run(
        ["python", "-m", "src.data.ingest"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    logger.info("STDOUT: %s", result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"Ingest script failed:\n{result.stderr}")
    try:
        import pandas as pd  # noqa: PLC0415
        rows = len(pd.read_csv(INGESTED_PATH))
    except Exception:
        rows = 0
    _push_pipeline_metrics(pipeline_rows_ingested=float(rows), pipeline_ingest_success=1.0)
    return {"returncode": result.returncode, "rows_ingested": rows}


def task_trigger_dvc(**context):
    """Start retraining if drift is found."""
    ti = context.get("ti")
    drift_result = ti.xcom_pull(task_ids="check_drift") if ti else None
    drift_detected = drift_result.get("drift_detected", False) if drift_result else False

    if not drift_detected:
        logger.info("No drift detected — skipping GitHub Actions trigger.")
        return {"skipped": True}

    # Running inside GitHub Actions — CI runner drives the second dvc repro
    if os.environ.get("GITHUB_ACTIONS") == "true":
        logger.info("CI context detected — skipping GitHub dispatch; runner will run dvc repro.")
        _push_pipeline_metrics(pipeline_dvc_triggered=1.0)
        return {"skipped": True, "reason": "ci_context"}

    github_pat  = os.environ.get("GITHUB_PAT", "")
    github_repo = os.environ.get("GITHUB_REPO", "r1sha13h/DA5402_Project")

    # Run DVC repro locally if flag set
    if not github_pat:
        if os.environ.get("LOCAL_DVC_REPRO") == "true":
            logger.info("LOCAL_DVC_REPRO=true — running dvc repro locally.")
            model_path = os.path.join(PROJECT_ROOT, "models", "latest_model.pt")
            env = os.environ.copy()
            if os.path.exists(model_path):
                env["FINETUNE_MODEL_PATH"] = model_path
                logger.info("Fine-tuning from existing model: %s", model_path)
            else:
                logger.warning("No existing model found at %s — training from scratch.", model_path)
            proc = subprocess.Popen(
                ["dvc", "repro"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=PROJECT_ROOT, env=env,
            )
            for line in proc.stdout:
                logger.info("[dvc] %s", line.rstrip())
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"dvc repro failed (rc={proc.returncode})")
            _push_pipeline_metrics(pipeline_dvc_triggered=1.0)
            return {"triggered": True, "reason": "local_dvc_repro"}
        logger.warning("GITHUB_PAT not set — cannot trigger GitHub Actions workflow.")
        return {"skipped": True, "reason": "no_pat"}

    api_url = (
        f"https://api.github.com/repos/{github_repo}"
        "/actions/workflows/ci.yml/dispatches"
    )
    headers = {
        "Authorization": f"Bearer {github_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": "main", "inputs": {"run_full_pipeline": "true"}}

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        if response.status_code == 204:
            logger.info("GitHub Actions workflow dispatched successfully.")
            _push_pipeline_metrics(pipeline_dvc_triggered=1.0)
            return {"triggered": True, "status_code": 204}
        logger.warning("GitHub dispatch HTTP %d: %s", response.status_code, response.text[:500])
        _push_pipeline_metrics(pipeline_dvc_triggered=0.0)
        return {"triggered": False, "status_code": response.status_code}
    except requests.RequestException as exc:
        raise RuntimeError(f"GitHub Actions dispatch failed: {exc}") from exc


def task_pipeline_complete(**context):
    """Mark run success and reset drift gauge after alert window."""
    logger.info("Pipeline complete.")
    _push_pipeline_metrics(pipeline_complete=1.0)

    # Wait for alert cycle if drift found (scrapes/rules/notifications)
    ti = context.get("ti")
    drift_result = ti.xcom_pull(task_ids="check_drift") if ti else None
    if drift_result and drift_result.get("drift_detected"):
        # Skip wait in CI (stack is short-lived)
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
            logger.info("Drift detected — skipping 75s alert-wait (GITHUB_ACTIONS=true).")
            _push_pipeline_metrics(pipeline_drift_detected=0.0)
        else:
            logger.info("Drift was detected — waiting 75s for alert to fire, then resetting.")
            time.sleep(75)
            _push_pipeline_metrics(pipeline_drift_detected=0.0)
            logger.info("Drift gauge reset to 0 — alert will resolve on next scrape.")
    return {"status": "complete"}


# DAG

with DAG(
    dag_id="spendsense_ingestion_pipeline",
    default_args=DEFAULT_ARGS,
    description="SpendSense data ingestion, drift detection, and conditional retraining",
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

    route_on_drift = BranchPythonOperator(
        task_id="route_on_drift",
        python_callable=task_route_on_drift,
    )

    combine_data = PythonOperator(
        task_id="combine_data",
        python_callable=task_combine_data,
    )

    run_ingest = PythonOperator(
        task_id="run_ingest",
        python_callable=task_run_ingest,
    )

    trigger_dvc = PythonOperator(
        task_id="trigger_dvc",
        python_callable=task_trigger_dvc,
    )

    pipeline_complete = PythonOperator(
        task_id="pipeline_complete",
        python_callable=task_pipeline_complete,
        trigger_rule="none_failed_min_one_success",
    )

    # Dependencies
    (
        verify_raw_data
        >> validate_schema
        >> check_nulls
        >> check_drift
        >> route_on_drift
    )

    # Drift path
    route_on_drift >> combine_data >> run_ingest >> trigger_dvc >> pipeline_complete

    # No-drift shortcut
    route_on_drift >> pipeline_complete
