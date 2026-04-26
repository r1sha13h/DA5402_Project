# Test Plan — SpendSense

## Acceptance Criteria

| Criterion | Threshold | Status |
|---|---|---|
| Test macro F1-score | ≥ 0.70 | ✅ Achieved: 98.72% |
| Test accuracy | ≥ 0.70 | ✅ Achieved: 98.75% |
| API latency (p95) | < 200ms | ✅ Verified via Prometheus histogram |
| Unit test suite | All tests pass (0 failures) | ✅ 68/68 pass |
| Code coverage | ≥ 60% | ✅ 66.3% (CI enforced) |
| Error rate in production | < 5% | ✅ Alertmanager fires at > 5% |

---

## Test Cases

### Module: src/data/ingest.py

| TC# | Test Case | Expected Output | Status |
|---|---|---|---|
| TC01 | Schema validation passes on valid DataFrame | No exception raised | Pass |
| TC02 | Schema fails on missing `category` column | ValueError | Pass |
| TC03 | Schema fails on wrong description column type | ValueError | Pass |
| TC04 | Null check: no change on clean DataFrame | Same row count | Pass |
| TC05 | Null rows are dropped | Output has fewer rows | Pass |
| TC06 | Unknown categories are filtered | Filtered to known categories only | Pass |
| TC07 | Categories: passes when all categories known | Full DataFrame returned | Pass |
| TC08 | End-to-end ingest writes output CSV | Output file exists, correct shape | Pass |

### Module: src/data/preprocess.py

| TC# | Test Case | Expected Output | Status |
|---|---|---|---|
| TC09 | Tokenizer lowercases text | ["zomato", "payment"] | Pass |
| TC10 | Tokenizer strips punctuation | No ₹ or ! in tokens | Pass |
| TC11 | Empty string tokenizes to empty list | [] | Pass |
| TC12 | Punctuation-only string returns empty list | [] | Pass |
| TC13 | Vocab contains PAD at 0, UNK at 1 | vocab["<PAD>"] == 0 | Pass |
| TC14 | min_freq filters rare words | Word appearing once not in vocab | Pass |
| TC15 | max_vocab_size cap respected | len(vocab) ≤ max_size + 2 | Pass |
| TC16 | Encoded shape is (n, max_seq_len) | array shape (2, 10) | Pass |
| TC17 | Short sequences are padded | Remaining positions are 0 | Pass |
| TC18 | Long sequences are truncated | Only first N tokens kept | Pass |
| TC19 | Unknown words encoded as UNK (index 1) | Encoded as index 1 | Pass |
| TC20 | Full preprocess produces all artefacts | 9 output files created | Pass |

### Module: src/models/model.py

| TC# | Test Case | Expected Output | Status |
|---|---|---|---|
| TC21 | Output shape single sample | (1, 10) logits | Pass |
| TC22 | Output shape batch | (8, 10) logits | Pass |
| TC23 | Output shape with variable seq_len | (4, 10) logits | Pass |
| TC24 | PAD embedding is zero | model.embedding.weight[0] is zero vector | Pass |
| TC25 | Backward pass has no NaN gradients | All gradients finite | Pass |
| TC26 | Eval mode is deterministic | Identical outputs for same input | Pass |
| TC27 | Single-layer model initialises without error | Forward pass succeeds | Pass |

### Module: backend/app/main.py — core endpoints

| TC# | Test Case | Expected Output | Status |
|---|---|---|---|
| TC28 | /health returns 200 | {"status": "ok"} | Pass |
| TC29 | /ready returns 200 when model loaded | {"ready": true} | Pass |
| TC30 | /predict returns category + confidence | 200, predicted_category present | Pass |
| TC31 | /predict returns 10 scores in all_scores | all_scores has 10 keys | Pass |
| TC32 | /predict empty description → 422 | 422 Unprocessable Entity | Pass |
| TC33 | /predict missing body → 422 | 422 Unprocessable Entity | Pass |
| TC34 | /predict/batch returns correct total | total == len(descriptions) | Pass |
| TC35 | /predict/batch empty list → 422 | 422 Unprocessable Entity | Pass |
| TC36 | /metrics returns Prometheus format | "spendsense_" in response body | Pass |
| TC37 | /models returns current_run_id and runs | 200, both keys present | Pass |
| TC38 | /models runs field is a list | runs is list type | Pass |
| TC39 | /models/switch success path | 200, status="ok" | Pass |
| TC40 | /models/switch missing run_id → 422 | 422 Unprocessable Entity | Pass |
| TC41 | /models/switch empty run_id → 422 | 422 Unprocessable Entity | Pass |
| TC42 | /models/switch load failure → 500 | 500 Internal Server Error | Pass |

### Module: backend/app/main.py — /feedback endpoint

| TC# | Test Case | Expected Output | Status |
|---|---|---|---|
| TC43 | /feedback correct prediction records entry | 200, status="ok" | Pass |
| TC44 | /feedback incorrect prediction still records | 200, status="ok" | Pass |
| TC45 | /feedback missing required fields → 422 | 422 Unprocessable Entity | Pass |
| TC46 | /feedback with optional transaction_id | 200 | Pass |

### Module: backend/app/predictor.py — SpendSensePredictor

| TC# | Test Case | Expected Output | Status |
|---|---|---|---|
| TC47 | list_mlflow_runs: returns list from mocked MLflow | list with 1 entry, run_id present | Pass |
| TC48 | list_mlflow_runs: no experiment returns [] | [] | Pass |
| TC49 | list_mlflow_runs: exception returns [] | [] | Pass |
| TC50 | load_from_mlflow: artifact error returns False | False, model is None | Pass |
| TC51 | load_from_mlflow: leaves model None on failure | not instance.is_ready | Pass |

### Module: airflow/dags/ingestion_dag.py

| TC# | Test Case | Expected Output | Status |
|---|---|---|---|
| TC52 | verify_raw_data: passes when file exists | Returns dict with exists=True | Pass |
| TC53 | verify_raw_data: raises when file missing | FileNotFoundError | Pass |
| TC54 | validate_schema: passes on valid CSV | Returns columns dict | Pass |
| TC55 | validate_schema: raises on missing column | ValueError | Pass |
| TC56 | check_nulls: no change on clean data | total_nulls == 0 | Pass |
| TC57 | check_nulls: null rows reported correctly | total_nulls == expected count | Pass |
| TC58 | check_drift: skips when no baseline exists | drift_detected == False | Pass |
| TC59 | check_drift: no drift on similar data | drift_detected == False | Pass |
| TC60 | check_drift: drift detected on skewed data | drift_detected == True, drift_details present | Pass |
| TC61 | task_run_ingest: skips in CI mode (GITHUB_ACTIONS=true) | {"skipped": True, "reason": "ci_mode"} | Pass |
| TC62 | task_run_ingest: success calls ingest subprocess | returncode == 0 | Pass |
| TC63 | task_run_ingest: failure raises RuntimeError | RuntimeError raised | Pass |
| TC64 | trigger_dvc: skips when drift=False | skipped == True | Pass |
| TC65 | trigger_dvc: skips when PAT not set | skipped == True | Pass |
| TC66 | trigger_dvc: triggers GitHub Actions on drift | triggered == True, status_code == 204 | Pass |
| TC67 | trigger_dvc: non-204 response handled gracefully | triggered == False, status_code returned | Pass |
| TC68 | trigger_dvc: network error raises RuntimeError | RuntimeError raised | Pass |

---

## Integration / System Tests

| # | Test Case | Tool | Expected Output |
|---|---|---|---|
| S1 | Full DVC pipeline runs end-to-end | `dvc repro` | All 4 stages complete, metrics written |
| S2 | Evaluation F1 meets threshold | CI metric check step | test_f1_macro ≥ 0.70 |
| S3 | Docker services start and are healthy | `docker compose up` | All 8 services healthy |
| S4 | Frontend connects to backend and predicts | Streamlit UI | Prediction displayed for sample input |
| S5 | Prometheus scrapes FastAPI metrics | Prometheus target page | Status = Up |
| S6 | Grafana dashboard loads with data | Browser → Grafana | SpendSense dashboard visible with panels |
| S7 | Airflow DAG runs successfully | Airflow UI | All 9 tasks green |
| S8 | CI pipeline completes all 3 jobs | GitHub Actions | All jobs pass, smoke tests green |

---

## Test Report Summary

| Category | Total | Passed | Failed |
|---|---|---|---|
| Unit tests (pytest) | 68 | 68 | 0 |
| Integration tests | 8 | 8 | 0 |
| **Total** | **76** | **76** | **0** |

**Latest CI run:** #24951097395 — All 3 jobs passed

*Reproduce unit tests:*
```bash
source venv/bin/activate
pytest tests/ -v --cov=src --cov=backend --cov-report=term-missing
```
