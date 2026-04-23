# Test Plan — SpendSense

## Acceptance Criteria

| Criterion | Threshold |
|---|---|
| Test macro F1-score | ≥ 0.70 |
| Test accuracy | ≥ 0.70 |
| API latency (p95) | < 200ms |
| Unit test suite | All tests pass (0 failures) |
| Code coverage | ≥ 60% |
| Error rate in production | < 5% |

---

## Test Cases

### Module: src/data/ingest.py

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC01 | Schema validation passes | Valid DataFrame with description, amount, category | No exception | Pass |
| TC02 | Schema fails on missing column | DataFrame without 'category' | ValueError | Pass |
| TC03 | Null rows are dropped | DataFrame with 2 null rows out of 5 | Output has 3 rows | Pass |
| TC04 | Unknown categories filtered | DataFrame with 'Unknown' category | Filtered to 0 rows | Pass |
| TC05 | End-to-end ingest writes output CSV | Valid raw CSV | Output file exists, correct shape | Pass |

### Module: src/data/preprocess.py

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC06 | Tokenizer lowercases text | "Zomato Payment" | ["zomato", "payment"] | Pass |
| TC07 | Tokenizer strips punctuation | "₹350 payment!" | No ₹ or ! in tokens | Pass |
| TC08 | Empty string tokenizes to empty list | "" | [] | Pass |
| TC09 | Vocab contains PAD at 0, UNK at 1 | Any texts | vocab["<PAD>"] == 0 | Pass |
| TC10 | min_freq filters rare words | "rare" appearing once | Not in vocab (min_freq=2) | Pass |
| TC11 | Encoded shape is (n, max_seq_len) | 2 texts, seq_len=10 | array shape (2, 10) | Pass |
| TC12 | Short sequences are padded | "hello" → 1 token | Remaining 9 positions are 0 | Pass |
| TC13 | Long sequences are truncated | 100-token sequence | Only first 5 tokens kept | Pass |
| TC14 | Full preprocess produces all artefacts | 100-row DataFrame | 9 output files created | Pass |

### Module: src/models/model.py

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC15 | Output shape single sample | (1, 20) input | (1, 10) logits | Pass |
| TC16 | Output shape batch | (8, 20) input | (8, 10) logits | Pass |
| TC17 | PAD embedding is zero | model.embedding.weight[0] | zero vector | Pass |
| TC18 | Backward pass has no NaN gradients | 4 samples | All gradients finite | Pass |
| TC19 | Eval mode is deterministic | Same input twice | Identical outputs | Pass |

### Module: backend/app/main.py

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC20 | /health returns 200 | GET /health | {"status": "ok"} | Pass |
| TC21 | /ready returns 200 (model loaded) | GET /ready | {"ready": true} | Pass |
| TC22 | /predict returns category + confidence | POST /predict | 200, predicted_category present | Pass |
| TC23 | /predict returns 10 scores | POST /predict | all_scores has 10 keys | Pass |
| TC24 | /predict empty description → 422 | POST /predict {"description": ""} | 422 | Pass |
| TC25 | /predict missing body → 422 | POST /predict {} | 422 | Pass |
| TC26 | /predict/batch returns correct count | 2 descriptions | total == 2 | Pass |
| TC27 | /predict/batch empty list → 422 | {"descriptions": []} | 422 | Pass |
| TC28 | /metrics returns Prometheus format | GET /metrics | "spendsense_" in body | Pass |
| TC29 | /models returns current_run_id and runs list | GET /models | 200, both keys present | Pass |
| TC30 | /models runs field is a list | GET /models | runs is list type | Pass |
| TC31 | /models/switch success path | POST /models/switch valid run_id | 200, status="ok" | Pass |
| TC32 | /models/switch missing run_id → 422 | POST /models/switch {} | 422 | Pass |
| TC33 | /models/switch empty run_id → 422 | POST /models/switch {"run_id": ""} | 422 | Pass |
| TC34 | /models/switch load failure → 500 | POST /models/switch, load fails | 500 | Pass |

### Module: backend/app/main.py — /feedback endpoint

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC59 | /feedback correct prediction records entry | correct prediction + tmp_path | 200, status="ok" | Pass |
| TC60 | /feedback incorrect prediction still records | wrong prediction + tmp_path | 200, status="ok" | Pass |
| TC61 | /feedback missing required fields → 422 | {"description": "test"} only | 422 | Pass |
| TC62 | /feedback with optional transaction_id | full payload + transaction_id | 200 | Pass |

### Module: backend/app/predictor.py — SpendSensePredictor

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC63 | list_mlflow_runs: returns list from mocked MLflow | mock experiment + runs | list with 1 entry, run_id="abc123" | Pass |
| TC64 | list_mlflow_runs: no experiment returns [] | mock returns None | [] | Pass |
| TC65 | list_mlflow_runs: exception returns [] | mock raises Exception | [] | Pass |
| TC66 | load_from_mlflow: artifact error returns False | mock raises Exception | False, model is None | Pass |
| TC67 | load_from_mlflow: leaves model None on failure | bad run ID | not instance.is_ready | Pass |

### Module: src/data/ingest.py (additional)

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC35 | Schema fails on wrong description column type | DataFrame with int description | ValueError | Pass |
| TC36 | Null check: no change on clean DataFrame | DataFrame with no nulls | Same row count | Pass |
| TC37 | Categories: passes when all categories known | DataFrame with known categories | Full DataFrame returned | Pass |

### Module: src/data/preprocess.py (additional)

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC38 | Tokenizer on punctuation-only string | "!@#$%" | [] (empty list) | Pass |
| TC39 | Vocab respects max_vocab_size cap | 1000 texts, max_size=10 | len(vocab) ≤ 12 (incl. PAD, UNK) | Pass |
| TC40 | Encoder maps unknown words to UNK | Word absent from vocab | Encoded as index 1 | Pass |

### Module: src/models/model.py (additional)

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC41 | Output shape with variable seq_len | (4, 15) input | (4, 10) logits | Pass |
| TC42 | Single-layer model initialises without dropout | num_layers=1 | Forward pass succeeds | Pass |

### Module: airflow/dags/ingestion_dag.py

| TC# | Test Case | Input | Expected Output | Status |
|---|---|---|---|---|
| TC43 | verify_raw_data: passes when file exists | File present with rows | No exception raised | Pass |
| TC44 | verify_raw_data: raises when file missing | File absent | FileNotFoundError | Pass |
| TC45 | validate_schema: passes on valid CSV | Valid schema CSV | No exception | Pass |
| TC46 | validate_schema: raises on missing column | CSV missing 'category' col | ValueError | Pass |
| TC47 | check_nulls: no change on clean data | CSV with no nulls | Full row count preserved | Pass |
| TC48 | check_nulls: null rows reported correctly | CSV with null rows | Null rows flagged | Pass |
| TC49 | check_drift: skips when no baseline exists | No baseline file | Returns "skipped" | Pass |
| TC50 | check_drift: no drift on similar data | Low mean-shift CSV | Returns "no_drift" | Pass |
| TC51 | check_drift: drift detected on shifted data | High mean-shift CSV | Returns "drift" | Pass |
| TC52 | run_ingest: success calls ingest subprocess | subprocess succeeds | Completes without raise | Pass |
| TC53 | run_ingest: failure raises AirflowException | subprocess non-zero exit | AirflowException raised | Pass |
| TC54 | trigger_dvc: skips when drift=False | XCom drift=False | "not_triggered" returned | Pass |
| TC55 | trigger_dvc: skips when PAT not set | PAT env var unset | "not_triggered" returned | Pass |
| TC56 | trigger_dvc: triggers GitHub Actions on drift | PAT set, drift=True | POST dispatched, 204 received | Pass |
| TC57 | trigger_dvc: non-204 response handled gracefully | API returns 400 | "not_triggered" returned | Pass |
| TC58 | trigger_dvc: network error raises RuntimeError | requests raises exception | RuntimeError raised | Pass |

### Integration / System Tests

| TC# | Test Case | Tool | Expected Output |
|---|---|---|---|
| TC29 | Full DVC pipeline runs end-to-end | `dvc repro` | All 5 stages complete successfully |
| TC30 | Evaluation F1 meets threshold | CI metric check | test_f1_macro ≥ 0.70 |
| TC31 | Docker services start cleanly | `docker compose up` | All 8 services healthy |
| TC32 | Frontend connects to backend | Streamlit UI | Prediction displayed for sample input |
| TC33 | Prometheus scrapes FastAPI metrics | Prometheus target | Up status |
| TC34 | Grafana dashboard loads | Browser → Grafana | SpendSense dashboard visible |
| TC35 | Airflow DAG runs successfully | Airflow UI | All 6 tasks green |

---

## Test Report Summary

| Category | Total | Passed | Failed |
|---|---|---|---|
| Unit tests (pytest) | 67 | 67 | 0 |
| Integration tests | 7 | 7 | 0 |
| **Total** | **74** | **74** | **0** |

*Run `pytest tests/ -v --cov=src --cov=backend` to reproduce unit test results.*
