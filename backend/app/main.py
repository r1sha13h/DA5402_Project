"""SpendSense FastAPI backend — REST API for transaction classification.

Endpoints:
    POST /predict          — single prediction
    POST /predict/batch    — batch prediction
    GET  /health           — liveness probe
    GET  /ready            — readiness probe (model-loaded check)
    GET  /metrics          — Prometheus metrics exposition
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from backend.app.monitoring import (
    BATCH_SIZE,
    MODEL_LOADED,
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
    HealthResponse,
    PredictRequest,
    PredictResponse,
    ReadyResponse,
)

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
        return ReadyResponse(ready=True, model_loaded=True)
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


@app.get("/metrics", tags=["Monitoring"])
def metrics():
    """Expose Prometheus metrics in text format."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
