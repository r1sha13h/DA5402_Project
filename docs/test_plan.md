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

### Integration / System Tests

| TC# | Test Case | Tool | Expected Output |
|---|---|---|---|
| TC29 | Full DVC pipeline runs end-to-end | `dvc repro` | All 5 stages complete successfully |
| TC30 | Evaluation F1 meets threshold | CI metric check | test_f1_macro ≥ 0.70 |
| TC31 | Docker services start cleanly | `docker compose up` | All 6 services healthy |
| TC32 | Frontend connects to backend | Streamlit UI | Prediction displayed for sample input |
| TC33 | Prometheus scrapes FastAPI metrics | Prometheus target | Up status |
| TC34 | Grafana dashboard loads | Browser → Grafana | SpendSense dashboard visible |
| TC35 | Airflow DAG runs successfully | Airflow UI | All 6 tasks green |

---

## Test Report Summary

| Category | Total | Passed | Failed |
|---|---|---|---|
| Unit tests (pytest) | 28 | 28 | 0 |
| Integration tests | 7 | 7 | 0 |
| **Total** | **35** | **35** | **0** |

*Run `pytest tests/ -v --cov=src --cov=backend` to reproduce unit test results.*
