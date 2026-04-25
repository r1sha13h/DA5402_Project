"""SpendSense FastAPI backend — REST API for transaction classification.

Endpoints:
    POST /predict          — single prediction
    POST /predict/batch    — batch prediction
    GET  /health           — liveness probe
    GET  /ready            — readiness probe (model-loaded check)
    GET  /metrics          — Prometheus metrics exposition
"""

import json
import logging
import os
import time
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from backend.app.monitoring import (
    BATCH_SIZE,
    DRIFT_SCORE,
    FEEDBACK_TOTAL,
    MODEL_LOADED,
    MODEL_SWITCHES,
    PREDICTION_CATEGORY,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    record_request,
)
from backend.app.predictor import predictor
from backend.app.schemas import (
    BatchPredictItem,
    BatchPredictRequest,
    BatchPredictResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    PredictRequest,
    PredictResponse,
    ReadyResponse,
    SwitchModelRequest,
)

_FEEDBACK_LOG = Path("feedback/feedback.jsonl")
_FEATURE_BASELINE = Path(
    os.environ.get("FEATURE_BASELINE_PATH", "data/processed/feature_baseline.json")
)
_DRIFT_THRESHOLD = 0.10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

APP_VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model artefacts on startup."""
    logger.info("Loading SpendSense model artefacts ...")
    success = predictor.load()
    MODEL_LOADED.set(1 if success else 0)
    if not success:
        logger.warning("Model failed to load — /ready will return 503.")
    yield
    logger.info("Shutting down SpendSense backend.")


app = FastAPI(
    title="SpendSense API",
    description="Expense category classifier for bank transaction descriptions.",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health() -> HealthResponse:
    """Liveness probe — always returns 200 if the process is alive."""
    REQUEST_COUNT.labels(endpoint="/health", status="200").inc()
    return HealthResponse(status="ok", version=APP_VERSION)


@app.get("/ready", response_model=ReadyResponse, tags=["Health"])
def ready() -> ReadyResponse:
    """Readiness probe — returns 200 only if the model is loaded."""
    if predictor.is_ready:
        REQUEST_COUNT.labels(endpoint="/ready", status="200").inc()
        msg = f"run_id={predictor.current_run_id}" if predictor.current_run_id else "disk"
        return ReadyResponse(ready=True, model_loaded=True, message=f"Model source: {msg}")
    REQUEST_COUNT.labels(endpoint="/ready", status="503").inc()
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Model not loaded yet.",
    )


@app.post("/predict", response_model=PredictResponse, tags=["Prediction"])
def predict(request: PredictRequest) -> PredictResponse:
    """Predict expense category for a single transaction description.

    Args:
        request: JSON body containing the transaction description.

    Returns:
        Predicted category, confidence score, and full score distribution.
    """
    start = time.perf_counter()
    try:
        category, confidence, all_scores = predictor.predict(request.description)
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/predict").observe(elapsed)
        REQUEST_COUNT.labels(endpoint="/predict", status="200").inc()
        PREDICTION_CATEGORY.labels(category=category).inc()
        record_request(success=True)
        logger.info("Predicted '%s' (conf=%.3f) for: %s", category, confidence,
                    request.description[:60])
        return PredictResponse(
            description=request.description,
            predicted_category=category,
            confidence=confidence,
            all_scores=all_scores,
        )
    except RuntimeError as exc:
        REQUEST_COUNT.labels(endpoint="/predict", status="503").inc()
        record_request(success=False)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(exc)) from exc
    except Exception as exc:
        REQUEST_COUNT.labels(endpoint="/predict", status="500").inc()
        record_request(success=False)
        logger.exception("Prediction error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Internal prediction error.") from exc


@app.post("/predict/batch", response_model=BatchPredictResponse, tags=["Prediction"])
def predict_batch(request: BatchPredictRequest) -> BatchPredictResponse:
    """Predict expense categories for a batch of transaction descriptions.

    Args:
        request: JSON body containing a list of descriptions.

    Returns:
        List of prediction results with confidence scores.
    """
    start = time.perf_counter()
    try:
        BATCH_SIZE.observe(len(request.descriptions))
        results_raw = predictor.predict_batch(request.descriptions)
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/predict/batch").observe(elapsed)
        REQUEST_COUNT.labels(endpoint="/predict/batch", status="200").inc()
        record_request(success=True)

        items = []
        for desc, (cat, conf, scores) in zip(request.descriptions, results_raw):
            PREDICTION_CATEGORY.labels(category=cat).inc()
            items.append(BatchPredictItem(
                description=desc,
                predicted_category=cat,
                confidence=conf,
                all_scores=scores,
            ))
        return BatchPredictResponse(results=items, total=len(items))
    except RuntimeError as exc:
        REQUEST_COUNT.labels(endpoint="/predict/batch", status="503").inc()
        record_request(success=False)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(exc)) from exc
    except Exception as exc:
        REQUEST_COUNT.labels(endpoint="/predict/batch", status="500").inc()
        record_request(success=False)
        logger.exception("Batch prediction error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Internal batch prediction error.") from exc


@app.get("/models", tags=["Model Management"])
def list_models():
    """List available MLflow experiment runs for model selection."""
    runs = predictor.list_mlflow_runs()
    return {
        "current_run_id": predictor.current_run_id,
        "runs": runs,
    }


@app.post("/models/switch", tags=["Model Management"])
def switch_model(request: SwitchModelRequest):
    """Switch the active model to one from a specific MLflow run.

    Args:
        request: JSON body with 'run_id' field (validated by Pydantic).
    """
    run_id = request.run_id
    success = predictor.load_from_mlflow(run_id)
    if success:
        MODEL_LOADED.set(1)
        MODEL_SWITCHES.inc()
        return {"status": "ok", "run_id": run_id, "message": "Model switched successfully."}
    raise HTTPException(
        status_code=500,
        detail=f"Failed to load model from MLflow run {run_id}.",
    )


@app.post("/feedback", response_model=FeedbackResponse, tags=["Feedback"])
def feedback(request: FeedbackRequest) -> FeedbackResponse:
    """Collect ground truth labels for production performance tracking.

    Args:
        request: JSON body with description, predicted_category, actual_category.

    Returns:
        Confirmation that feedback was recorded.
    """
    _FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": time.time(),
        "description": request.description,
        "predicted_category": request.predicted_category,
        "actual_category": request.actual_category,
        "transaction_id": request.transaction_id,
        "correct": request.predicted_category == request.actual_category,
    }
    with open(_FEEDBACK_LOG, "a") as fh:
        fh.write(json.dumps(entry) + "\n")
    REQUEST_COUNT.labels(endpoint="/feedback", status="200").inc()
    FEEDBACK_TOTAL.inc()
    logger.info(
        "Feedback recorded: predicted=%s actual=%s correct=%s",
        request.predicted_category, request.actual_category, entry["correct"],
    )
    return FeedbackResponse(status="ok", message="Feedback recorded.")


@app.get("/drift", tags=["Monitoring"])
def drift_check():
    """Compare recent feedback label distribution against the training baseline.

    Uses actual_category from feedback.jsonl and label_distribution from
    feature_baseline.json. Flags any category whose share shifted by more than
    10 percentage points.
    """
    if not predictor.is_ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Model not loaded.")

    if not _FEATURE_BASELINE.exists():
        return {"status": "no_baseline",
                "message": str(_FEATURE_BASELINE) + " not found."}

    with open(_FEATURE_BASELINE) as fh:
        baseline_data = json.load(fh)

    raw_dist = baseline_data.get("label_distribution", {})
    total_baseline = sum(raw_dist.values()) or 1
    classes = predictor.label_encoder.classes_
    baseline_norm = {
        classes[int(k)]: v / total_baseline
        for k, v in raw_dist.items()
        if int(k) < len(classes)
    }

    if not _FEEDBACK_LOG.exists():
        return {
            "status": "no_feedback",
            "message": "No feedback collected yet.",
            "feedback_samples": 0,
            "baseline_distribution": {k: round(v, 4) for k, v in baseline_norm.items()},
        }

    counts: Counter = Counter()
    with open(_FEEDBACK_LOG) as fh:
        for line in fh:
            line = line.strip()
            if line:
                entry = json.loads(line)
                cat = entry.get("actual_category") or entry.get("predicted_category", "")
                if cat:
                    counts[cat] += 1

    total_feedback = sum(counts.values())
    if total_feedback < 100:
        return {
            "status": "insufficient_data",
            "message": f"Need at least 100 feedback samples to detect drift (have {total_feedback}).",
            "feedback_samples": total_feedback,
            "baseline_distribution": {k: round(v, 4) for k, v in baseline_norm.items()},
        }

    feedback_norm = {cat: count / total_feedback for cat, count in counts.items()}

    drift_flags = {}
    for cat in set(list(baseline_norm.keys()) + list(feedback_norm.keys())):
        base = baseline_norm.get(cat, 0.0)
        curr = feedback_norm.get(cat, 0.0)
        shift = abs(curr - base)
        if shift > _DRIFT_THRESHOLD:
            drift_flags[cat] = {
                "baseline": round(base, 4),
                "current": round(curr, 4),
                "shift": round(shift, 4),
            }

    max_shift = max((v["shift"] for v in drift_flags.values()), default=0.0)
    DRIFT_SCORE.set(max_shift)
    return {
        "status": "drift_detected" if drift_flags else "ok",
        "drift_flags": drift_flags,
        "feedback_samples": total_feedback,
        "baseline_distribution": {k: round(v, 4) for k, v in baseline_norm.items()},
        "feedback_distribution": {k: round(v, 4) for k, v in feedback_norm.items()},
    }


@app.get("/metrics", tags=["Monitoring"])
def metrics():
    """Expose Prometheus metrics in text format."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
