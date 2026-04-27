# Low-Level Design (LLD) — SpendSense

## 1. API Endpoint Specifications

### POST /predict

**Description:** Predict expense category for a single transaction description.

**Request Body:**
```json
{ "description": "Zomato food delivery payment" }
```

| Field | Type | Constraints | Description |
|---|---|---|---|
| description | string | min_length=1, max_length=500 | Raw transaction description |

**Response (200 OK):**
```json
{
  "description": "Zomato food delivery payment",
  "predicted_category": "Food & Dining",
  "confidence": 0.91,
  "all_scores": {
    "Food & Dining": 0.91,
    "Transportation": 0.02,
    "Utilities & Services": 0.01,
    "...": 0.0
  }
}
```

| Field | Type | Description |
|---|---|---|
| description | string | Echo of the input |
| predicted_category | string | Highest-probability category |
| confidence | float [0,1] | Softmax probability of predicted class |
| all_scores | dict[str, float] | Softmax scores for all 10 categories |

**Error Responses:**
- `422 Unprocessable Entity` — validation error (empty description)
- `503 Service Unavailable` — model not loaded
- `500 Internal Server Error` — unexpected inference error

---

### POST /predict/batch

**Description:** Predict categories for multiple descriptions in one call.

**Request Body:**
```json
{ "descriptions": ["Zomato payment", "Uber ride", "Netflix subscription"] }
```

| Field | Type | Constraints |
|---|---|---|
| descriptions | list[string] | min_items=1, max_items=500 |

**Response (200 OK):**
```json
{
  "results": [
    {
      "description": "Zomato payment",
      "predicted_category": "Food & Dining",
      "confidence": 0.89,
      "all_scores": { "...": 0.0 }
    }
  ],
  "total": 3
}
```

---

### GET /health

**Description:** Liveness probe — returns 200 if process is alive.

**Response (200 OK):**
```json
{ "status": "ok", "version": "1.0.0" }
```

---

### GET /ready

**Description:** Readiness probe — returns 200 only if model is loaded.

**Response (200 OK):** `{ "ready": true, "model_loaded": true }`

**Response (503):** `{ "detail": "Model not loaded yet." }`

---

### GET /models

**Description:** List all available MLflow FINISHED runs whose run name is `bilstm_training` or `bilstm_finetune` (i.e. model-producing runs only — `evaluation` sub-runs are excluded). Used by the UI for the model-switch picker and by the demo for hot-swap.

**Response (200 OK):**
```json
{
  "current_run_id": "c58d6422395d4bebb2c17ce87c5ec37d",
  "runs": [
    {
      "run_id": "c58d6422395d4bebb2c17ce87c5ec37d",
      "experiment_id": "1",
      "status": "FINISHED",
      "start_time": 1714000000000,
      "metrics": { "test_f1_macro": 0.9872, "test_accuracy": 0.9875 }
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| current_run_id | string \| null | Run ID of the currently active model |
| runs | list | All FINISHED MLflow runs with their metrics |

---

### POST /models/switch

**Description:** Hot-swap the active model to one from a specific MLflow run (no container restart required).

**Request Body:**
```json
{ "run_id": "c58d6422395d4bebb2c17ce87c5ec37d" }
```

| Field | Type | Constraints | Description |
|---|---|---|---|
| run_id | string | min_length=1 | MLflow run ID to load model artefacts from |

**Response (200 OK):**
```json
{ "status": "ok", "run_id": "c58d6422395d4bebb2c17ce87c5ec37d", "message": "Model switched successfully." }
```

**Error Responses:**
- `422 Unprocessable Entity` — missing or empty run_id
- `500 Internal Server Error` — artefacts not found or load failed

---

### POST /feedback

**Description:** Collect ground truth labels for production performance tracking. Appends one JSON line to `feedback/feedback.jsonl`.

**Request Body:**
```json
{
  "description": "Zomato food delivery payment",
  "predicted_category": "Food & Dining",
  "actual_category": "Food & Dining",
  "transaction_id": "txn_001"
}
```

| Field | Type | Constraints | Description |
|---|---|---|---|
| description | string | min_length=1, max_length=500 | Original transaction description |
| predicted_category | string | min_length=1 | Category the model predicted |
| actual_category | string | min_length=1 | Correct ground truth category |
| transaction_id | string | optional | Caller-supplied transaction identifier |

**Response (200 OK):**
```json
{ "status": "ok", "message": "Feedback recorded." }
```

**Storage:** Each entry is a JSON object with keys `timestamp`, `description`, `predicted_category`, `actual_category`, `transaction_id`, `correct` (bool).

---

### GET /drift

**Description:** Compare recent feedback label distribution against the training baseline. Flags categories that have shifted more than 10 percentage points.

**Response (200 OK):**
```json
{
  "status": "ok",
  "drift_flags": {},
  "feedback_samples": 42,
  "baseline_distribution": { "Food & Dining": 0.1062, "Transportation": 0.1079 },
  "feedback_distribution": { "Food & Dining": 0.214, "Transportation": 0.095 }
}
```

| Field | Type | Description |
|---|---|---|
| status | string | `"ok"`, `"drift_detected"`, `"no_feedback"`, `"no_baseline"` |
| drift_flags | object | Per-category `{baseline, current, shift}` for shifted categories |
| feedback_samples | int | Number of feedback entries analysed |
| baseline_distribution | object | Training-time category proportions |
| feedback_distribution | object | Current feedback category proportions |

Requires ≥ 100 feedback samples to compute drift; returns `"no_feedback"` otherwise.

**Error Responses:**
- `503 Service Unavailable` — model not loaded (label encoder unavailable)

---

### GET /metrics

**Description:** Prometheus metrics in text format. Scraped by Prometheus every 10s.

**Response:** Prometheus exposition format (text/plain)

Key metrics exposed:
| Metric | Type | Description |
|---|---|---|
| spendsense_requests_total | Counter | Total requests, labelled by endpoint and status |
| spendsense_request_latency_seconds | Histogram | Request latency distribution |
| spendsense_error_rate | Gauge | Rolling error rate (last 100 requests) |
| spendsense_predictions_by_category_total | Counter | Predictions per category |
| spendsense_model_loaded | Gauge | 1 if model loaded, 0 otherwise |
| spendsense_batch_size | Histogram | Batch size distribution |
| spendsense_feedback_total | Counter | Total feedback entries received |
| spendsense_drift_score | Gauge | Maximum per-category drift score from last /drift call |
| spendsense_model_switches_total | Counter | Number of model hot-swaps |

---

## 2. Module Breakdown

### src/data/ingest.py
- `validate_schema(df) → None` — raises ValueError on schema mismatch
- `validate_nulls(df) → pd.DataFrame` — drops null rows
- `validate_categories(df) → pd.DataFrame` — filters unknown categories
- `log_baseline_statistics(df, output_dir) → None` — writes `baseline_stats.json` (row count + category distribution for Airflow drift detector)
- `ingest(raw_path, output_path) → None`

### src/data/preprocess.py
- `tokenize(text) → list[str]` — whitespace tokenisation + lowercase + punctuation strip
- `build_vocab(texts, max_vocab_size, min_freq) → dict` — top-N tokens with min frequency; `<PAD>` at 0, `<UNK>` at 1
- `encode_texts(texts, vocab, max_seq_len) → np.ndarray` — pads/truncates to `max_seq_len`
- `save_baseline(X, y, output_dir) → None` — writes `feature_baseline.json` (label distribution for `/drift` endpoint)
- `preprocess(ingested_path, output_dir, params) → None`

### src/models/model.py
- `BiLSTMClassifier(vocab_size, embed_dim, hidden_dim, num_classes, num_layers, dropout)`
  - `forward(x: LongTensor) → Tensor` — Embedding → BiLSTM → Dropout → Linear → ReLU → Dropout → Linear

### src/models/train.py
- `load_processed_data(processed_dir) → tuple`
- `run_epoch(model, loader, optimizer, criterion, device, training) → (loss, acc, f1)`
- `main() → None` — reads `FINETUNE_MODEL_PATH` env var to switch between full training and fine-tuning; logs to MLflow; auto-promotes to Staging

### src/models/evaluate.py
- `evaluate(processed_dir, params) → dict` — computes accuracy, macro F1, per-class F1, confusion matrix; exits non-zero if F1 < threshold
- `main() → None`

### backend/app/predictor.py
- `SpendSensePredictor`
  - `load() → bool` — loads artefacts from disk on startup; applies INT8 quantization on CPU
  - `load_from_mlflow(run_id) → bool` — downloads and activates artefacts from an MLflow run
  - `list_mlflow_runs() → list[dict]` — returns all FINISHED runs with metrics
  - `predict(description) → (category, confidence, all_scores)`
  - `predict_batch(descriptions) → list`

### backend/app/main.py
- FastAPI app with lifespan, CORS middleware, all 9 endpoints

### backend/app/monitoring.py
- All Prometheus metric objects: `REQUEST_COUNT`, `REQUEST_LATENCY`, `FEEDBACK_TOTAL`, `DRIFT_SCORE`, `MODEL_SWITCHES`, `PREDICTION_CATEGORY`, `BATCH_SIZE`, `MODEL_LOADED`

### backend/app/schemas.py
- Pydantic models: `PredictRequest`, `PredictResponse`, `BatchPredictRequest`, `BatchPredictResponse`, `FeedbackRequest`, `SwitchModelRequest`

### frontend/Home.py
- Single prediction page; 6 example buttons (use `session_state.get` not `pop` to survive form-submit rerun); feedback form post-prediction

### frontend/pages/1_Batch_Predict.py
- Three tabs: CSV upload, paste text, HDFC XLS
- `_clean_hdfc_narration(s)` strips UPI/NEFT/RTGS/IMPS/POS/ATM prefixes from raw bank narrations before inference

### frontend/pages/2_Pipeline_Status.py
- Service health grid, Prometheus metric counters, DVC DAG diagram (Graphviz), Airflow DAG run history with task-level breakdown

---

## 3. Data Models

### Vocabulary
```python
vocab: dict[str, int]
# { "<PAD>": 0, "<UNK>": 1, "zomato": 2, ... }  — up to 10,002 entries
```

### Label Encoder
```python
label_encoder.classes_: np.ndarray  # 10 categories, alphabetically sorted
# ["Charity & Donations", "Entertainment & Recreation", ...]
```

### DVC Pipeline Outputs
| Stage | Output |
|---|---|
| ingest | data/ingested/transactions.csv, data/ingested/baseline_stats.json |
| preprocess | data/processed/{X,y}_{train,val,test}.npy, vocab.pkl, label_encoder.pkl, feature_baseline.json |
| train | models/latest_model.pt, metrics/train_metrics.json |
| evaluate | metrics/eval_metrics.json |

### feedback.jsonl entry
```json
{
  "timestamp": "2026-04-26T07:30:00",
  "description": "Zomato payment",
  "predicted_category": "Food & Dining",
  "actual_category": "Food & Dining",
  "transaction_id": null,
  "correct": true
}
```

---

## 4. Exception Handling

| Layer | Exception | Handling |
|---|---|---|
| Ingest | FileNotFoundError | sys.exit(1) with error log |
| Ingest | ValueError (schema) | sys.exit(1) with error log |
| Evaluate | F1 < threshold | sys.exit(1) (fails DVC/CI stage) |
| Backend predict | RuntimeError (model not loaded) | HTTP 503 |
| Backend predict | General Exception | HTTP 500 + logged |
| Backend /models/switch | Artefact load failure | HTTP 500 + logged |
| Frontend | requests.ConnectionError | st.error with user message |
| Airflow task_trigger_dvc | requests.RequestException | RuntimeError raised → task fails |

---

## 5. Logging Standards

All modules use Python's standard `logging` module at INFO level.

Format: `%(asctime)s %(levelname)s %(message)s`

Key log events:
- Data loaded / rows count
- Validation passed / failed (with counts)
- Epoch metrics (loss, F1)
- Model saved / loaded (with path and run_id)
- API request served (category + confidence)
- Drift detected / not detected (with per-category shifts)
