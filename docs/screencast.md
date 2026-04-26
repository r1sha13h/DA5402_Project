# SpendSense — Live Screencast Script

**Use:** Online evaluation panel demo via screen share. Follow each section in order. Bracketed notes like `[TAB: Chrome]` are actions; plain text is spoken narration.

**Estimated runtime:** 13–15 minutes

---

## Before You Start (do not narrate)

```bash
docker compose ps          # all 8 containers should be Up
curl -s http://localhost:8000/ready   # should return {"ready": true}
```

Reset feedback for a clean drift demo:
```bash
cp /dev/null feedback/feedback.jsonl
```

Have these browser tabs open and ready:
- GitHub Actions (latest run)
- http://localhost:8080 (Airflow)
- http://localhost:5000 (MLflow)
- http://localhost:8501 (Streamlit)
- http://localhost:8000/docs (FastAPI Swagger)
- http://localhost:9090 (Prometheus)
- http://localhost:3001 (Grafana)

---

## Step 1 — CI/CD Pipeline (~2 min)

`[TAB: GitHub Actions — latest successful run]`

"I'll start with the outermost layer — continuous integration. SpendSense uses a three-job GitHub Actions pipeline running on a self-hosted GPU runner.

The first job handles code quality: it runs flake8 linting and our full 68-test pytest suite, including coverage enforcement. This takes about 40 seconds.

`[Click on Job 2]`

The second job is the ML pipeline. It starts by splitting the dataset: 90% goes to a baseline file, 10% goes to a deliberately skewed drift file to simulate distribution shift. Then it starts MLflow, Prometheus, Grafana, and the other infrastructure services.

DVC Run 1 trains the BiLSTM classifier from scratch on the 90% baseline data. After training, we start the Airflow container and trigger the ingestion DAG, which detects drift in the 10% file and combines the datasets. Then DVC Run 2 fine-tunes the model for one additional epoch on the combined data.

`[Click on Job 3]`

The third job downloads only the essential artifacts — the model weights, vocabulary, label encoder, and MLflow tracking database — around 30 megabytes total. It starts the FastAPI and Streamlit containers and runs smoke tests to confirm prediction endpoints are working. Total pipeline time: about 13 minutes.

The key point here is the F1 quality gate: if the model doesn't hit 0.70 macro F1, the evaluate stage exits non-zero and the pipeline fails. We're achieving 98.7%, so that gate is comfortably cleared."

---

## Step 2 — Airflow: Data Ingestion DAG (~2 min)

`[TAB: Airflow — http://localhost:8080]`

"Moving one layer in: Apache Airflow orchestrates our data ingestion pipeline. The DAG ID is `spendsense_ingestion_pipeline`, running on a daily schedule.

`[Click on the DAG, then Graph view]`

The pipeline has nine tasks. The first three — verify_raw_data, validate_schema, and check_nulls — are data quality checks. They confirm the file exists, the required columns are present, and there are no unexpected nulls.

The fourth task, check_drift, is the critical one. It loads the baseline category distribution we computed during the original ingest and compares it against the incoming data. If any category shifts by more than 10 percentage points, drift is flagged.

`[Click on route_on_drift]`

Task five is a BranchPythonOperator: if drift was detected, it routes to combine_data, which merges the baseline data with the drift file and any feedback corrections our users have submitted. That flows into run_ingest, which re-validates the combined dataset, and then trigger_dvc, which dispatches a GitHub Actions workflow to kick off retraining.

If there's no drift, we skip directly to pipeline_complete.

`[Click on a recent successful run, then on check_drift → Logs]`

Here you can see the log output from the last drift check, showing the per-category distribution comparison and the drift decision."

---

## Step 3 — DVC: Reproducible ML Pipeline (~1 min)

`[Switch to terminal]`

```bash
source venv/bin/activate
dvc dag
```

"The ML pipeline itself is managed by DVC, which gives us reproducibility guarantees. There are four stages: ingest, preprocess, train, and evaluate.

Each stage has explicit inputs and outputs declared in dvc.yaml. DVC computes MD5 hashes of every input and output and records them in dvc.lock. If I run `dvc repro` and nothing has changed, all four stages are skipped — DVC confirms the outputs are identical to what's in the lock file.

This means any experiment is fully reproducible: a git commit hash plus a run ID in MLflow plus the dvc.lock file gives you exactly the model that was produced."

---

## Step 4 — MLflow: Experiment Tracking (~2 min)

`[TAB: MLflow — http://localhost:5000]`

"MLflow tracks every experiment. Navigate to the SpendSense experiment and you'll see two types of runs.

`[Click on the SpendSense experiment, show run list]`

Runs tagged `bilstm_training` are full training runs from scratch — that's DVC Run 1. Runs tagged `bilstm_finetune` are the one-epoch fine-tuning passes — DVC Run 2.

`[Click into a bilstm_training run]`

Each run logs 10 hyperparameters — embedding dim, hidden size, number of LSTM layers, dropout, batch size, and so on. Under Metrics you can see the per-epoch training and validation F1 curve. Scroll down to Artifacts.

`[Click on Artifacts]`

The confusion matrix heatmap is logged here as a PNG. You can see the model distinguishes all 10 expense categories with very high confidence — the diagonal is dominant.

`[Click Models in the top nav]`

In the Model Registry, the SpendSense model is automatically promoted to Staging after each successful training run. This gives us a versioned, auditable history of every model we've ever shipped."

---

## Step 5 — Streamlit UI (~3 min)

`[TAB: Streamlit — http://localhost:8501]`

"The user-facing interface is built in Streamlit. Let's walk through all three pages.

**Home — single prediction**

`[Type in the description box or click an example button]`

I'll click the Zomato example button to pre-fill the input.

`[Click Classify]`

The prediction comes back instantly: Food & Dining, 97% confidence. The confidence bar chart shows scores for all 10 categories, and below it is a plain-English explanation of what the confidence score means.

Now I'll submit a piece of feedback. Say the model predicted Food & Dining but I know this was actually a grocery run I'd categorise differently.

`[Select a category from the feedback dropdown, click Submit Feedback]`

This calls POST /feedback on the backend and appends the entry to feedback.jsonl on disk.

**Batch Predict**

`[Click Batch Predict in the sidebar]`

`[Click the Paste Descriptions tab, paste 5–6 descriptions]`

For batch processing, paste multiple descriptions — one per line — and click Classify All. Results come back in a table with category and confidence for each row, and the donut chart shows the spending distribution.

`[Click CSV tab]`

You can also upload a CSV file with a `description` column, or — and this is a special feature — upload an HDFC bank statement in XLS format directly.

`[Click HDFC Statement tab]`

For HDFC statements, SpendSense automatically detects the transaction table, filters to debit transactions, and strips the standard bank prefixes — UPI slash, NEFT slash, POS space, and so on — before classifying.

**Pipeline Status**

`[Click Pipeline Status in the sidebar]`

`[Point to the health grid]`

This page shows the live health of all seven services. FastAPI, MLflow, Airflow, Prometheus, Grafana, Pushgateway, and Alertmanager — all green.

`[Scroll down to the DVC DAG section]`

The DVC pipeline DAG is rendered inline using Graphviz.

`[Scroll to Airflow Run History]`

And here's the Airflow DAG run history with task-level status for each recent run — you can see the full task chain and which branch was taken."

---

## Step 6 — FastAPI: REST API (~1 min)

`[TAB: FastAPI — http://localhost:8000/docs]`

"The backend is a FastAPI application exposing nine endpoints documented here with automatic OpenAPI schemas.

`[Scroll through the endpoint list]`

POST /predict for single classification, POST /predict/batch for bulk, GET /models to list all MLflow runs with their F1 scores, POST /models/switch for zero-downtime model hot-swap, POST /feedback to log corrections, GET /drift to check distribution shift from accumulated feedback, and GET /metrics in Prometheus exposition format.

`[Click POST /predict, click Try it out, enter a description, Execute]`

Running predict interactively — you can see the response schema: predicted_category, confidence as a float, and all_scores with probabilities for all 10 categories."

---

## Step 7 — Prometheus + Grafana: Observability (~2 min)

`[TAB: Prometheus — http://localhost:9090]`

"Prometheus collects metrics from five instrumented components. The FastAPI backend exposes a /metrics endpoint that Prometheus scrapes every 15 seconds. The training, evaluation, Airflow, and Streamlit components push metrics to Pushgateway.

`[Type in query box: spendsense_requests_total, click Execute]`

Here's the cumulative request counter. You can see it broken down by endpoint and HTTP status.

`[Switch to: spendsense_request_latency_seconds_bucket]`

And here's the latency histogram. Prometheus evaluates our 11 alert rules against these time series — HighErrorRate fires if the 5-minute error rate exceeds 5%, DataDriftDetected fires when the Airflow drift flag is set, and so on.

`[TAB: Grafana — http://localhost:3001, credentials admin/admin]`

Grafana visualises the same data in seven panels: Request Rate, Error Rate, Feedback Count, Drift Score, Latency Percentiles showing P50, P95, and P99, Model Info showing the current loaded run, and Alert Firing History.

`[Point to the Latency Percentiles panel]`

The P95 latency is well under our 200ms target — typically around 15–20ms on CPU with INT8 quantization applied."

---

## Step 8 — Model Hot-Swap (~1 min)

`[Switch to terminal]`

"Finally, let me demonstrate zero-downtime model switching. The backend can swap to any MLflow run without restarting the container.

```bash
curl -s http://localhost:8000/models | python3 -m json.tool
```

`[Run the command, point out the run IDs in the response]`

I can see two runs here. Let me switch to the first training run.

```bash
curl -s -X POST http://localhost:8000/models/switch \
  -H 'Content-Type: application/json' \
  -d '{"run_id": "<paste_run_id>"}' | python3 -m json.tool
```

`[Run, show status: ok response]`

Status OK — the model was downloaded from MLflow, INT8-quantized, and hot-loaded into the predictor singleton. No container restart, no downtime. This is our primary rollback mechanism if a new training run produces a worse model."

---

## Closing (~30 seconds)

"That covers the full end-to-end stack: GitHub Actions CI/CD at the outer layer, Airflow orchestrating daily data ingestion and drift detection, DVC providing reproducible pipeline execution, MLflow tracking every experiment, FastAPI serving predictions via REST, Streamlit as the user interface, and Prometheus with Grafana providing observability with 11 alert rules.

The feedback loop closes the cycle: user corrections flow through POST /feedback into feedback.jsonl, the GET /drift endpoint surfaces distribution shift, Airflow picks it up on the next daily run, and the GitHub Actions pipeline automatically retrains and redeploys.

Happy to take questions on any component."
