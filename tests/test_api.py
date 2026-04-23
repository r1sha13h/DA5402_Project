"""Unit tests for the FastAPI backend endpoints."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ── Mock predictor before importing app ───────────────────────────────────────

_MOCK_RUNS = [
    {"run_id": "abc123", "f1_macro": 0.987, "timestamp": "2026-04-23 11:33:00"},
    {"run_id": "def456", "f1_macro": 0.951, "timestamp": "2026-04-17 09:10:00"},
]


@pytest.fixture(scope="module")
def mock_predictor():
    """Patch the predictor singleton so tests do not require a trained model."""
    mock = MagicMock()
    mock.is_ready = True
    mock.current_run_id = "abc123"
    mock.list_mlflow_runs.return_value = _MOCK_RUNS
    mock.load_from_mlflow.return_value = True
    mock.predict.return_value = (
        "Food & Dining",
        0.91,
        {
            "Food & Dining": 0.91, "Transportation": 0.02, "Utilities & Services": 0.01,
            "Entertainment & Recreation": 0.01, "Shopping & Retail": 0.01,
            "Healthcare & Medical": 0.01, "Financial Services": 0.01,
            "Income": 0.00, "Government & Legal": 0.01, "Charity & Donations": 0.01,
        },
    )
    mock.predict_batch.return_value = [
        (
            "Food & Dining",
            0.88,
            {"Food & Dining": 0.88, "Transportation": 0.03, "Utilities & Services": 0.02,
             "Entertainment & Recreation": 0.01, "Shopping & Retail": 0.01,
             "Healthcare & Medical": 0.01, "Financial Services": 0.01,
             "Income": 0.01, "Government & Legal": 0.01, "Charity & Donations": 0.01},
        ),
        (
            "Transportation",
            0.92,
            {"Food & Dining": 0.02, "Transportation": 0.92, "Utilities & Services": 0.01,
             "Entertainment & Recreation": 0.01, "Shopping & Retail": 0.01,
             "Healthcare & Medical": 0.01, "Financial Services": 0.01,
             "Income": 0.00, "Government & Legal": 0.01, "Charity & Donations": 0.00},
        ),
    ]
    return mock


@pytest.fixture(scope="module")
def client(mock_predictor):
    """TestClient with the predictor patched to avoid model loading."""
    with patch("backend.app.predictor.predictor", mock_predictor):
        with patch("backend.app.main.predictor", mock_predictor):
            from backend.app.main import app  # noqa: PLC0415
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c


# ── Tests: /health ────────────────────────────────────────────────────────────

def test_health_returns_200(client):
    """GET /health returns HTTP 200 and status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


# ── Tests: /ready ─────────────────────────────────────────────────────────────

def test_ready_returns_200_when_model_loaded(client):
    """GET /ready returns 200 when model is loaded."""
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["model_loaded"] is True


# ── Tests: POST /predict ──────────────────────────────────────────────────────

def test_predict_single_returns_category(client):
    """POST /predict returns predicted_category and confidence."""
    resp = client.post("/predict", json={"description": "Zomato food delivery"})
    assert resp.status_code == 200
    body = resp.json()
    assert "predicted_category" in body
    assert "confidence" in body
    assert "all_scores" in body
    assert 0.0 <= body["confidence"] <= 1.0


def test_predict_returns_all_scores(client):
    """Response all_scores contains an entry for every category."""
    resp = client.post("/predict", json={"description": "Zomato food delivery"})
    scores = resp.json()["all_scores"]
    assert len(scores) == 10


def test_predict_empty_description_returns_422(client):
    """Empty description string triggers Pydantic validation error (422)."""
    resp = client.post("/predict", json={"description": ""})
    assert resp.status_code == 422


def test_predict_missing_body_returns_422(client):
    """Missing JSON body returns 422."""
    resp = client.post("/predict", json={})
    assert resp.status_code == 422


# ── Tests: POST /predict/batch ────────────────────────────────────────────────

def test_predict_batch_returns_correct_count(client):
    """Batch response total matches the number of input descriptions."""
    resp = client.post("/predict/batch",
                       json={"descriptions": ["Zomato payment", "Uber ride"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["results"]) == 2


def test_predict_batch_empty_list_returns_422(client):
    """Empty list triggers Pydantic min_items validation (422)."""
    resp = client.post("/predict/batch", json={"descriptions": []})
    assert resp.status_code == 422


# ── Tests: GET /metrics ───────────────────────────────────────────────────────

def test_metrics_endpoint_returns_prometheus_format(client):
    """GET /metrics returns Prometheus text format (contains # HELP)."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "spendsense" in resp.text


# ── Tests: GET /models ────────────────────────────────────────────────────────

def test_list_models_returns_runs(client):
    """GET /models returns a list of MLflow runs and the current run ID."""
    resp = client.get("/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "runs" in body
    assert "current_run_id" in body
    assert len(body["runs"]) == 2


def test_list_models_run_structure(client):
    """Each run in GET /models has run_id and f1_macro fields."""
    resp = client.get("/models")
    run = resp.json()["runs"][0]
    assert "run_id" in run
    assert "f1_macro" in run


# ── Tests: POST /models/switch ────────────────────────────────────────────────

def test_switch_model_success(client):
    """POST /models/switch with a valid run_id returns ok status."""
    resp = client.post("/models/switch", json={"run_id": "abc123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["run_id"] == "abc123"


def test_switch_model_missing_run_id_returns_422(client):
    """POST /models/switch with empty body returns 422 validation error."""
    resp = client.post("/models/switch", json={})
    assert resp.status_code == 422


def test_switch_model_empty_run_id_returns_422(client):
    """POST /models/switch with empty string run_id returns 422."""
    resp = client.post("/models/switch", json={"run_id": ""})
    assert resp.status_code == 422


def test_switch_model_failure_returns_500(client, mock_predictor):
    """POST /models/switch returns 500 when load_from_mlflow fails."""
    mock_predictor.load_from_mlflow.return_value = False
    resp = client.post("/models/switch", json={"run_id": "bad_run_id"})
    assert resp.status_code == 500
    mock_predictor.load_from_mlflow.return_value = True
