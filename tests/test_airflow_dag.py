"""Unit tests for the SpendSense Airflow ingestion DAG task callables.

Each task function is tested in isolation using mocks so no Airflow
scheduler, real filesystem, or network connection is required.
"""

import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, mock_open, patch

# ---------------------------------------------------------------------------
# Stub out airflow imports so the module can be imported without Airflow
# installed in the test environment.
# ---------------------------------------------------------------------------
airflow_stub = types.ModuleType("airflow")
airflow_dag_stub = types.ModuleType("airflow.models")
airflow_operators_stub = types.ModuleType("airflow.operators")
airflow_python_stub = types.ModuleType("airflow.operators.python")


class _DAG:  # noqa: D101
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _PythonOperator:  # noqa: D101
    def __init__(self, *args, **kwargs):
        pass

    def __rshift__(self, other):
        return other


airflow_stub.DAG = _DAG
airflow_python_stub.PythonOperator = _PythonOperator

sys.modules.setdefault("airflow", airflow_stub)
sys.modules.setdefault("airflow.models", airflow_dag_stub)
sys.modules.setdefault("airflow.operators", airflow_operators_stub)
sys.modules.setdefault("airflow.operators.python", airflow_python_stub)

# Ensure the real `requests` library is in sys.modules so that other test
# modules (e.g. test_api.py via mlflow) are not broken by a stub. Only fall
# back to a minimal stub when the library is not installed at all.
try:
    import requests as _real_requests  # noqa: F401
except ImportError:
    _requests_stub = types.ModuleType("requests")
    _requests_stub.post = MagicMock()

    class _RequestException(Exception):
        """Minimal stand-in for requests.RequestException."""

    _requests_stub.RequestException = _RequestException
    sys.modules["requests"] = _requests_stub

# Import the DAG module directly from its file path to avoid collision with
# the local airflow/ project directory vs. the stubbed airflow package.
import importlib.util  # noqa: E402

_DAG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "airflow", "dags", "ingestion_dag.py")
)
_spec = importlib.util.spec_from_file_location("ingestion_dag", _DAG_PATH)
dag_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dag_module)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_context(xcom_data=None):
    """Return a minimal Airflow context dict with a stubbed TaskInstance."""
    ti = MagicMock()
    ti.xcom_pull.return_value = xcom_data
    return {"ti": ti}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTaskVerifyRawData(unittest.TestCase):

    @patch("os.path.exists", return_value=True)
    @patch("os.path.getsize", return_value=172_000_000)
    def test_file_exists(self, mock_size, mock_exists):
        result = dag_module.task_verify_raw_data(**_make_context())
        self.assertTrue(result["exists"])
        self.assertAlmostEqual(result["size_mb"], 164.1, delta=1)

    @patch("os.path.exists", return_value=False)
    def test_file_missing_raises(self, mock_exists):
        with self.assertRaises(FileNotFoundError):
            dag_module.task_verify_raw_data(**_make_context())


class TestTaskValidateSchema(unittest.TestCase):

    def _make_df(self, columns):
        """Create a minimal pandas-like DataFrame mock."""
        import pandas as pd
        data = {c: ["x"] for c in columns}
        return pd.DataFrame(data)

    @patch("pandas.read_csv")
    def test_valid_schema(self, mock_read):
        import pandas as pd
        mock_read.return_value = pd.DataFrame(
            {"description": ["foo"], "category": ["bar"]}
        )
        result = dag_module.task_validate_schema(**_make_context())
        self.assertIn("description", result["columns"])
        self.assertIn("category", result["columns"])

    @patch("pandas.read_csv")
    def test_missing_column_raises(self, mock_read):
        import pandas as pd
        mock_read.return_value = pd.DataFrame({"description": ["foo"]})
        with self.assertRaises(ValueError, msg="Should raise for missing 'category'"):
            dag_module.task_validate_schema(**_make_context())


class TestTaskCheckNulls(unittest.TestCase):

    @patch("pandas.read_csv")
    def test_no_nulls(self, mock_read):
        import pandas as pd
        mock_read.return_value = pd.DataFrame(
            {"description": ["foo", "bar"], "category": ["A", "B"]}
        )
        result = dag_module.task_check_nulls(**_make_context())
        self.assertEqual(result["total_nulls"], 0)

    @patch("pandas.read_csv")
    def test_with_nulls(self, mock_read):
        import pandas as pd
        mock_read.return_value = pd.DataFrame(
            {"description": ["foo", None], "category": ["A", None]}
        )
        result = dag_module.task_check_nulls(**_make_context())
        self.assertEqual(result["total_nulls"], 2)


class TestTaskCheckDrift(unittest.TestCase):

    baseline = {
        "category_distribution": {
            "Food & Dining": 500,
            "Transportation": 500,
        }
    }

    @patch("os.path.exists", return_value=False)
    @patch("pandas.read_csv")
    def test_no_baseline_skips(self, mock_read, mock_exists):
        import pandas as pd
        mock_read.return_value = pd.DataFrame({"category": ["Food & Dining"] * 10})
        result = dag_module.task_check_drift(**_make_context())
        self.assertFalse(result["drift_detected"])

    @patch("os.path.exists", return_value=True)
    @patch("pandas.read_csv")
    def test_no_drift(self, mock_read, mock_exists):
        import pandas as pd
        mock_read.return_value = pd.DataFrame(
            {"category": ["Food & Dining"] * 50 + ["Transportation"] * 50}
        )
        baseline_json = json.dumps(self.baseline)
        with patch("builtins.open", mock_open(read_data=baseline_json)):
            result = dag_module.task_check_drift(**_make_context())
        self.assertFalse(result["drift_detected"])

    @patch("os.path.exists", return_value=True)
    @patch("pandas.read_csv")
    def test_drift_detected(self, mock_read, mock_exists):
        import pandas as pd
        # Heavily skewed — almost all Food & Dining
        mock_read.return_value = pd.DataFrame(
            {"category": ["Food & Dining"] * 95 + ["Transportation"] * 5}
        )
        baseline_json = json.dumps(self.baseline)
        with patch("builtins.open", mock_open(read_data=baseline_json)):
            result = dag_module.task_check_drift(**_make_context())
        self.assertTrue(result["drift_detected"])
        self.assertIn("Transportation", result["drift_details"])


class TestTaskRunIngest(unittest.TestCase):

    @patch("subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        result = dag_module.task_run_ingest(**_make_context())
        self.assertEqual(result["returncode"], 0)

    @patch("subprocess.run")
    def test_failure_raises(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        with self.assertRaises(RuntimeError):
            dag_module.task_run_ingest(**_make_context())


class TestTaskTriggerDvc(unittest.TestCase):

    def test_skips_when_no_drift(self):
        ctx = _make_context(xcom_data={"drift_detected": False})
        result = dag_module.task_trigger_dvc(**ctx)
        self.assertTrue(result.get("skipped"))

    @patch.dict(os.environ, {"GITHUB_PAT": "", "GITHUB_REPO": "owner/repo"})
    def test_skips_when_no_pat(self):
        ctx = _make_context(xcom_data={"drift_detected": True})
        result = dag_module.task_trigger_dvc(**ctx)
        self.assertTrue(result.get("skipped"))

    @patch.dict(os.environ, {"GITHUB_PAT": "ghp_test", "GITHUB_REPO": "owner/repo"})
    def test_triggers_github_actions_on_drift(self):
        mock_response = MagicMock()
        mock_response.status_code = 204

        ctx = _make_context(xcom_data={"drift_detected": True})
        with patch.object(dag_module.requests, "post", return_value=mock_response) as mock_post:
            result = dag_module.task_trigger_dvc(**ctx)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        # Verify the correct API URL was hit
        self.assertIn("owner/repo", call_kwargs[0][0])
        self.assertIn("ci.yml/dispatches", call_kwargs[0][0])
        self.assertTrue(result.get("triggered"))
        self.assertEqual(result["status_code"], 204)

    @patch.dict(os.environ, {"GITHUB_PAT": "ghp_test", "GITHUB_REPO": "owner/repo"})
    def test_non_204_response_returns_not_triggered(self):
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        ctx = _make_context(xcom_data={"drift_detected": True})
        with patch.object(dag_module.requests, "post", return_value=mock_response):
            result = dag_module.task_trigger_dvc(**ctx)

        self.assertFalse(result.get("triggered"))
        self.assertEqual(result["status_code"], 403)

    @patch.dict(os.environ, {"GITHUB_PAT": "ghp_test", "GITHUB_REPO": "owner/repo"})
    def test_request_exception_raises_runtime_error(self):
        ctx = _make_context(xcom_data={"drift_detected": True})
        exc = dag_module.requests.RequestException("timeout")
        with patch.object(dag_module.requests, "post", side_effect=exc):
            with self.assertRaises(RuntimeError):
                dag_module.task_trigger_dvc(**ctx)


if __name__ == "__main__":
    unittest.main()
