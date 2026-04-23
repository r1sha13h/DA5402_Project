"""Prometheus Pushgateway client for the SpendSense Streamlit frontend."""

import os

try:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "http://localhost:9091")


def push_ui_event(predictions: int, errors: int, batch_items: int) -> None:
    """Push cumulative UI event counts to Prometheus Pushgateway.

    Args:
        predictions: Cumulative single predictions made this session.
        errors: Cumulative prediction errors this session.
        batch_items: Cumulative batch items classified this session.
    """
    if not _AVAILABLE:
        return
    try:
        registry = CollectorRegistry()
        Gauge(
            "spendsense_ui_predictions_total",
            "Cumulative single predictions made via Streamlit UI",
            registry=registry,
        ).set(predictions)
        Gauge(
            "spendsense_ui_errors_total",
            "Cumulative UI prediction errors",
            registry=registry,
        ).set(errors)
        Gauge(
            "spendsense_ui_batch_items_total",
            "Cumulative batch items classified via Streamlit UI",
            registry=registry,
        ).set(batch_items)
        push_to_gateway(PUSHGATEWAY_URL, job="spendsense_ui", registry=registry)
    except Exception:
        pass
