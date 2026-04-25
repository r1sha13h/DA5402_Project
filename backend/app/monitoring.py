"""Prometheus instrumentation for the SpendSense FastAPI backend."""

from prometheus_client import Counter, Gauge, Histogram

# ── Request counters ──────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "spendsense_requests_total",
    "Total number of prediction requests",
    ["endpoint", "status"],
)

# ── Latency histogram ─────────────────────────────────────────────────────────
REQUEST_LATENCY = Histogram(
    "spendsense_request_latency_seconds",
    "Request latency in seconds",
    ["endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.5],
)

# ── Error rate gauge (updated after every request) ───────────────────────────
ERROR_RATE = Gauge(
    "spendsense_error_rate",
    "Fraction of recent requests that returned an error (rolling window)",
)

# ── Prediction distribution ───────────────────────────────────────────────────
PREDICTION_CATEGORY = Counter(
    "spendsense_predictions_by_category_total",
    "Number of predictions per category",
    ["category"],
)

# ── Model info ────────────────────────────────────────────────────────────────
MODEL_LOADED = Gauge(
    "spendsense_model_loaded",
    "1 if the model is loaded and ready, 0 otherwise",
)

# ── Batch size histogram ──────────────────────────────────────────────────────
BATCH_SIZE = Histogram(
    "spendsense_batch_size",
    "Number of items per batch prediction request",
    buckets=[1, 5, 10, 25, 50, 100, 250, 500],
)

# ── Feedback, drift, and model-management metrics ─────────────────────────
FEEDBACK_TOTAL = Counter(
    "spendsense_feedback_total",
    "Total number of feedback entries recorded via POST /feedback",
)

DRIFT_SCORE = Gauge(
    "spendsense_drift_score",
    "Maximum per-category distribution shift from the last /drift check",
)

MODEL_SWITCHES = Counter(
    "spendsense_model_switches_total",
    "Total number of model hot-swap operations via POST /models/switch",
)

# ── Rolling window for error-rate calculation ─────────────────────────────────
_WINDOW = 100
_recent: list = []


def record_request(success: bool) -> None:
    """Update the rolling error-rate gauge.

    Args:
        success: True if the request completed without error.
    """
    global _recent
    _recent.append(0 if success else 1)
    if len(_recent) > _WINDOW:
        _recent = _recent[-_WINDOW:]
    if _recent:
        ERROR_RATE.set(sum(_recent) / len(_recent))
