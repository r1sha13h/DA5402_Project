# Data Description — SpendSense

## 1. Data Source

| Property | Value |
|---|---|
| Dataset | `nickmuchi/financial-classification` (HuggingFace) |
| Format | CSV — two columns: `description` (string), `category` (string) |
| Raw size | ~4,500,000 rows |
| Domain | Real bank transaction narrations (predominantly US-centric) |
| Augmentation | 118 real Indian bank transaction feedback entries added via the feedback loop |

The dataset contains raw transaction narrations as they appear in bank statements (e.g. `"POS ZOMATO 9148 MUMBAI"`, `"NEFT CR SALARY INFOSYS"`) paired with one of 10 expense category labels.

---

## 2. Target Classes (10 Categories)

| Label | Category | Example Transactions |
|---|---|---|
| 0 | Charity & Donations | NGO donation, temple donation |
| 1 | Entertainment & Recreation | Netflix, BookMyShow, gaming |
| 2 | Financial Services | Credit card payment, SIP, LIC premium |
| 3 | Food & Dining | Zomato, Swiggy, restaurant bill |
| 4 | Government & Legal | Tax payment, passport fees, court fees |
| 5 | Healthcare & Medical | Apollo pharmacy, lab tests |
| 6 | Income | Salary credit, freelance payment, refund |
| 7 | Shopping & Retail | Amazon, Flipkart, Myntra |
| 8 | Transportation | Uber, Ola, petrol pump |
| 9 | Utilities & Services | BESCOM bill, Jio recharge, internet |

Label indices are assigned alphabetically by `sklearn.LabelEncoder`.

---

## 3. Data Cleanup & Ingestion (DVC Stage 1 — `src/data/ingest.py`)

The raw CSV is cleaned in four sequential steps before any ML processing:

### Step 1 — Schema Validation
Asserts that both `description` and `category` columns are present and of string type. Fails the pipeline immediately if either column is missing.

### Step 2 — Null Removal
Rows with null values in `description` or `category` are logged and dropped.

### Step 3 — Category Filtering
Rows whose `category` value is not in the 10 expected labels are dropped. This removes any vendor-specific or ambiguous labels present in the original HuggingFace release.

### Step 4 — Deduplication
Exact duplicate `(description, category)` pairs are removed. This is the largest source of row reduction — the HuggingFace dataset contains many repeated transaction strings.

### Cleanup Results

| Stage | Rows |
|---|---|
| Raw download | ~4,500,000 |
| After null removal + category filter + deduplication | **1,343,517** |
| Eliminated | ~3,156,483 (~70%) |

After cleanup, the **category distribution is approximately balanced** (~130K–138K rows per category):

| Category | Count |
|---|---|
| Financial Services | 138,454 |
| Government & Legal | 138,401 |
| Utilities & Services | 137,366 |
| Shopping & Retail | 134,008 |
| Food & Dining | 133,932 |
| Transportation | 133,799 |
| Entertainment & Recreation | 133,570 |
| Healthcare & Medical | 132,582 |
| Charity & Donations | 131,232 |
| Income | 130,173 |

**Average description length:** 25.3 characters

### Outputs
- `data/ingested/transactions.csv` — cleaned dataset
- `data/ingested/baseline_stats.json` — row count, per-category distribution, avg description length; used by Airflow for daily drift comparison

---

## 4. CI/CD Data Splits (`scripts/create_drift_split.py`)

Before the DVC pipeline runs in CI, the raw dataset is split into two files to simulate a real-world drift scenario:

### 90% Baseline Split (`data/raw/transactions_90.csv`)
- **Rows:** ~4,050,939 (raw, before ingest cleanup)
- Stratified sample — preserves the original category distribution
- Used as `data/raw/transactions.csv` for **DVC Run 1** (full training from scratch)

### 10% Drift Split (`data/drift/transactions_drift.csv`)
- **Rows:** ~450,104 (raw)
- **Intentionally skewed** — the top-3 most frequent categories are oversampled to 75% of the slice, guaranteeing a >10 percentage-point distribution shift from the baseline
- Mechanism: remaining rows after the 90% stratified sample are reconstructed with 75% top-3 category rows + 25% remaining categories
- No synthetic data — all rows are genuine transactions from the original dataset
- Used by Airflow's daily `check_drift` task for drift detection

### Why This Design?
The 10% drift file mimics what happens in production when a model is deployed and real transaction patterns shift (e.g. seasonal spending, new merchant categories). By oversampling certain categories, the Airflow drift alert is guaranteed to fire on every CI run, exercising the full retraining loop.

---

## 5. Data Preprocessing (DVC Stage 2 — `src/data/preprocess.py`)

The cleaned ingested dataset is transformed into numerical arrays suitable for the BiLSTM model.

### Text Preprocessing
Each transaction description is:
1. Lowercased
2. Punctuation stripped (`re.sub(r"[^a-z0-9\s]", " ", text)`)
3. Whitespace-tokenised into word tokens

### Train / Validation / Test Split
Stratified split to preserve category proportions across all three sets:

| Split | Fraction | Approximate Rows (from 1.34M) |
|---|---|---|
| Train | 70% | ~940,000 |
| Validation | 15% | ~202,000 |
| Test | 15% | ~202,000 |

Split parameters from `params.yaml`: `test_size: 0.15`, `val_size: 0.15`, `seed: 42`.

### Vocabulary Construction
Built exclusively from the **training set** (no validation/test leakage):

| Parameter | Value |
|---|---|
| Max vocabulary size | 10,000 |
| Minimum word frequency | 2 |
| Special tokens | `<PAD>` (index 0), `<UNK>` (index 1) |
| Effective vocab size | 10,002 (10,000 words + PAD + UNK) |

### Sequence Encoding
Each description is encoded as a fixed-length integer sequence:
- Tokens mapped to vocabulary indices; unknown words → `<UNK>` (index 1)
- Sequences shorter than 50 tokens are right-padded with `<PAD>` (index 0)
- Sequences longer than 50 tokens are truncated on the right
- **Max sequence length:** 50 tokens (covers >99% of transaction descriptions)

**Average non-zero tokens per sequence:** 3.68 ± 1.13 (from `feature_baseline.json`) — most transaction narrations are short (3–5 meaningful words after stripping prefixes and codes).

### Outputs — `data/processed/`

| File | Description |
|---|---|
| `X_train.npy` | Encoded training sequences, shape `(~940K, 50)`, dtype `int32` |
| `X_val.npy` | Encoded validation sequences, shape `(~202K, 50)`, dtype `int32` |
| `X_test.npy` | Encoded test sequences, shape `(~202K, 50)`, dtype `int32` |
| `y_train.npy` | Integer labels for training set |
| `y_val.npy` | Integer labels for validation set |
| `y_test.npy` | Integer labels for test set |
| `vocab.pkl` | Python dict mapping word → integer index (used at inference) |
| `label_encoder.pkl` | `sklearn.LabelEncoder` instance mapping integer → category name (used at inference) |
| `feature_baseline.json` | Training-set statistics: avg non-zero tokens, label distribution; used by `GET /drift` |

---

## 6. Feedback Data (`feedback/feedback.jsonl`)

Users can submit corrections via `POST /feedback` in the Streamlit UI or directly through the API. Each entry is appended as a JSON line:

```json
{
  "timestamp": "2026-04-27T14:32:01",
  "description": "UPI-SWIGGY-PAY@ICICI",
  "predicted_category": "Shopping & Retail",
  "actual_category": "Food & Dining",
  "transaction_id": "txn_abc123",
  "correct": false
}
```

**Properties:**
- Append-only log — never overwritten by the system
- Bind-mounted into both the backend and Airflow containers
- Persisted across CI runs via explicit copy in the CI workflow
- When Airflow detects drift, `combine_data` extracts the `(description, actual_category)` pairs and merges them into the retraining corpus
- **Note:** Must be reset manually before a live demo (`cp /dev/null feedback/feedback.jsonl`) as it accumulates CI test entries

---

## 7. Data Drift Detection

Two independent drift detection mechanisms run in parallel:

### 7A — Airflow Daily Drift Check (`task_check_drift`)
Runs every day as part of the `spendsense_ingestion_pipeline` DAG.

- Compares the **category distribution** of `data/drift/transactions_drift.csv` against `data/ingested/baseline_stats.json`
- Flags drift when any category's proportion shifts by **>10 percentage points**
- If drift is detected → `combine_data` task merges all three sources and triggers retraining

### 7B — API Drift Endpoint (`GET /drift`)
Runs on-demand when called by the Streamlit Pipeline Status page or directly.

- Reads `feedback/feedback.jsonl`, extracts `actual_category` values
- Compares distribution against `data/processed/feature_baseline.json`
- Requires **≥100 feedback samples** to produce a result (avoids false positives from small samples)
- Flags any category with >10pp shift
- Sets the `DRIFT_SCORE` Prometheus gauge, which feeds the `DataDriftDetected` Grafana alert

---

## 8. Retraining Data Merge (`task_combine_data`)

When drift is detected, Airflow's `combine_data` task merges three sources into a single training file:

```
data/raw/transactions_90.csv      (~4.05M rows, 90% baseline)
    +
data/drift/transactions_drift.csv  (~450K rows, 10% drifted)
    +
feedback/feedback.jsonl            (user-corrected labels)
    ↓
data/raw/transactions.csv          (~4.5M rows, combined)
```

This combined file is then passed through the full DVC pipeline (ingest → preprocess → train → evaluate) as **DVC Run 2**, which fine-tunes from the Run 1 checkpoint for 1 epoch rather than training from scratch.

---

## 9. Data Flow Summary

```
HuggingFace (4.5M rows)
    │
    ▼
data/raw/transactions.csv
    │
    ├── create_drift_split.py
    │       ├── data/raw/transactions_90.csv   (90%, ~4.05M, stratified)
    │       └── data/drift/transactions_drift.csv  (10%, ~450K, intentionally skewed)
    │
    ▼ [DVC Stage 1 — ingest.py]
data/ingested/transactions.csv  (1,343,517 rows after null/dup/category cleanup)
data/ingested/baseline_stats.json
    │
    ▼ [DVC Stage 2 — preprocess.py]
data/processed/
    ├── X_train.npy / y_train.npy  (70%, ~940K rows)
    ├── X_val.npy   / y_val.npy    (15%, ~202K rows)
    ├── X_test.npy  / y_test.npy   (15%, ~202K rows)
    ├── vocab.pkl                  (10,002 tokens)
    ├── label_encoder.pkl          (10 classes)
    └── feature_baseline.json
    │
    ▼ [DVC Stage 3 — train.py]
models/latest_model.pt             (BiLSTM weights)
    │
    ▼ [DVC Stage 4 — evaluate.py]
metrics/eval_metrics.json          (F1, accuracy, confusion matrix)

[Feedback Loop]
POST /feedback → feedback/feedback.jsonl
GET  /drift    → compares vs feature_baseline.json (≥100 samples, >10pp threshold)

[Airflow Daily]
check_drift → compares transactions_drift.csv vs baseline_stats.json (>10pp threshold)
    └── if drift → combine_data → merge all sources → DVC Run 2 (fine-tune)
```

---

## 10. DVC Data Versioning

All data files are tracked by DVC, not Git (binary/large files). Content hashes are recorded in `dvc.lock`:

| Path | Tracked by |
|---|---|
| `data/raw/transactions.csv` | DVC |
| `data/raw/transactions_90.csv` | DVC |
| `data/drift/transactions_drift.csv` | DVC |
| `data/ingested/transactions.csv` | DVC |
| `data/ingested/baseline_stats.json` | DVC |
| `data/processed/*.npy` | DVC |
| `data/processed/vocab.pkl` | DVC |
| `data/processed/label_encoder.pkl` | DVC |
| `data/processed/feature_baseline.json` | DVC |
| `params.yaml` | Git |
| All source code (`src/`, `airflow/`, `backend/`) | Git |

**DVC remote:** `/home/rishabh/.dvc_remote_da5402` (local path on the runner machine).

To restore any prior data state: `git checkout <commit> && dvc checkout`
