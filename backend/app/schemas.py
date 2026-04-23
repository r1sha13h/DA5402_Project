"""Pydantic request/response schemas for the SpendSense FastAPI backend."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class PredictRequest(BaseModel):
    """Request body for single transaction prediction."""

    description: str = Field(
        ...,
        min_length=1,
        max_length=500,
        json_schema_extra={"example": "Zomato food delivery payment"},
    )


class PredictResponse(BaseModel):
    """Response body for single transaction prediction."""

    description: str
    predicted_category: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    all_scores: Dict[str, float]


class BatchPredictRequest(BaseModel):
    """Request body for batch transaction prediction."""

    descriptions: List[str] = Field(..., min_length=1, max_length=500)


class BatchPredictItem(BaseModel):
    """Single item within a batch prediction response."""

    description: str
    predicted_category: str
    confidence: float
    all_scores: Dict[str, float]


class BatchPredictResponse(BaseModel):
    """Response body for batch transaction prediction."""

    results: List[BatchPredictItem]
    total: int


class HealthResponse(BaseModel):
    """Response body for /health endpoint."""

    status: str
    version: str


class ReadyResponse(BaseModel):
    """Response body for /ready endpoint."""

    ready: bool
    model_loaded: bool
    message: Optional[str] = None


class SwitchModelRequest(BaseModel):
    """Request body for /models/switch endpoint."""

    run_id: str = Field(
        ...,
        min_length=1,
        description="MLflow run ID to load the model from.",
        json_schema_extra={"example": "c58d6422395d4bebb2c17ce87c5ec37d"},
    )


class FeedbackRequest(BaseModel):
    """Request body for /feedback endpoint — ground truth label collection."""

    description: str = Field(
        ..., min_length=1, max_length=500,
        json_schema_extra={"example": "Zomato food delivery payment"},
    )
    predicted_category: str = Field(
        ..., min_length=1,
        json_schema_extra={"example": "Food & Dining"},
    )
    actual_category: str = Field(
        ..., min_length=1,
        json_schema_extra={"example": "Food & Dining"},
    )
    transaction_id: Optional[str] = Field(
        None, json_schema_extra={"example": "txn_001"},
    )


class FeedbackResponse(BaseModel):
    """Response body for /feedback endpoint."""

    status: str
    message: str
