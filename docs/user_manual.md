# SpendSense — User Manual

A complete, non-technical guide for using SpendSense end-to-end. Read this once and you'll know how to:

- **Set up and start the application** on any computer with Docker installed
- **Make predictions** in three different ways (single, paste-many, file-upload)
- **Read the live monitoring dashboards** in Grafana to understand how the system is performing

> **Who this guide is for:** Anyone who wants to use SpendSense — no programming background required. If a step uses a command, copy-paste it exactly. Where a step is just clicking around in a web browser, screenshots aren't needed; the labels match what you see on screen.

---

## Table of Contents

1. [What SpendSense Does](#1-what-spendsense-does)
2. [System Requirements](#2-system-requirements)
3. [First-Time Setup](#3-first-time-setup-one-time)
4. [Starting the Application](#4-starting-the-application-every-time)
5. [Using the Streamlit Web Interface](#5-using-the-streamlit-web-interface)
   - 5.1 [Single Prediction (Home page)](#51-single-prediction-home-page)
   - 5.2 [Batch Prediction (Many at once)](#52-batch-prediction-many-at-once)
   - 5.3 [Pipeline Status (System health)](#53-pipeline-status-system-health)
6. [Reading the Grafana Dashboard](#6-reading-the-grafana-monitoring-dashboard)
7. [Stopping the Application](#7-stopping-the-application)
8. [Troubleshooting](#8-troubleshooting)
9. [Reference: 10 Expense Categories](#9-reference-the-10-expense-categories)

---

## 1. What SpendSense Does

Bank transaction descriptions are messy. Lines like:

- `POS ZOMATO 9148`
- `UPI/PHONEPE/AMAZON-IN/...`
- `NEFT-CR-RISHABH-SALARY`

mean nothing to a budgeting tool. **SpendSense automatically classifies each line into one of 10 expense categories** — Food, Transport, Shopping, Healthcare, and so on — using a neural network trained on 4.5 million real bank transactions.

You can use SpendSense in three ways:
- Type **one transaction** at a time and get an instant category
- Paste a **list of transactions** and get them all categorised
- Upload your **Bank statement (.xls)** directly and get a categorised CSV back

A built-in monitoring dashboard (Grafana) shows you how the system is performing in real time — request rate, response time, error count, and more.

---

## 2. System Requirements

You need:

| Requirement | Why | How to check |
|---|---|---|
| **Docker** + **Docker Compose** installed | All 8 services run as Docker containers | Run `docker --version` and `docker compose version` in a terminal — both should print a version |
| **8 GB RAM free** | The MLflow + backend + Airflow stack uses ~4 GB; the rest is headroom | Task Manager / Activity Monitor / `free -h` |
| **5 GB free disk space** | Docker images + model + dataset | `df -h` (Linux/Mac) or File Explorer (Windows) |
| **A modern web browser** | The interface is served over HTTP | Chrome, Firefox, Edge, Safari all work |
| **These ports must be free** | 5000, 8000, 8080, 8501, 9090, 9091, 9093, 3001 | Run `ss -tln` (Linux) — none of those should be listed |

You do **not** need: Python installed, a GPU, internet access (after first-time setup), or any cloud account.

---

## 3. First-Time Setup (one time)

> Skip this section if you've already run SpendSense before on this computer.

### Step 1 — Get the project files

```bash
git clone https://github.com/r1sha13h/DA5402_Project.git
cd DA5402_Project
```

This downloads about 50 MB of code and configuration files.

### Step 2 — Get the trained model

The trained model file (`models/latest_model.pt`, ~15 MB) is **not** included in the git repository. You have three options:

**Option A — Pull from DVC remote (fastest, ~30 sec):**
```bash
dvc pull
```

**Option B — Train it yourself from scratch (~15 min, requires GPU):**
```bash
source venv/bin/activate    # if a venv exists
dvc repro                   # runs the full data pipeline
```

**Option C — Let CI produce it for you:** push a commit to `main` on GitHub and download the `models/latest_model.pt` from the latest GitHub Actions run.

After this step, confirm the file exists:
```bash
ls -lh models/latest_model.pt
# Expected: -rw-r--r-- ... 15M ... models/latest_model.pt
```

### Step 3 (optional) — Configure email alerts

If you want the system to email you when something goes wrong (high error rate, drift detected, model crashed):

```bash
# Add to the .env file in project root
echo "ALERTMANAGER_SMTP_PASSWORD=your_gmail_app_password" >> .env
```

Skip this if you don't need email alerts. The application works fine without them.

That's it for setup. The rest of this manual is what you do **every time** you want to use SpendSense.

---

## 4. Starting the Application (every time)

In a terminal, from the project root:

```bash
docker compose up -d
```

This starts **all 8 services** in the background. The first run will take 1–2 minutes (Docker pulls images); subsequent runs take ~15 seconds.

### Verify everything is running

```bash
docker compose ps
```

You should see 8 containers, all in state `Up` or `running`:

```
NAME                       STATUS         PORTS
spendsense_backend         Up (healthy)   0.0.0.0:8000->8000/tcp
spendsense_frontend        Up             0.0.0.0:8501->8501/tcp
spendsense_mlflow          Up (healthy)   0.0.0.0:5000->5000/tcp
spendsense_airflow         Up (healthy)   0.0.0.0:8080->8080/tcp
spendsense_prometheus      Up             0.0.0.0:9090->9090/tcp
spendsense_pushgateway     Up             0.0.0.0:9091->9091/tcp
spendsense_grafana         Up             0.0.0.0:3001->3000/tcp
spendsense_alertmanager    Up             0.0.0.0:9093->9093/tcp
```

If a container shows `Restarting` for more than 30 seconds, see [Troubleshooting](#8-troubleshooting).

### Confirm the model is loaded

```bash
curl -s http://localhost:8000/ready
```

You should see: `{"ready":true,"model_loaded":true}`. If you see `false`, wait 20 seconds and retry — the model takes a moment to load on first start.

---

## 5. Using the Streamlit Web Interface

The Streamlit web app is the main way you interact with SpendSense. Open your browser to:

> **http://localhost:8501**

You'll see three pages in the left sidebar: **Home**, **Batch Predict**, and **Pipeline Status**.

### 5.1 Single Prediction (Home page)

**Use this when:** you want to quickly check what category one transaction belongs to.

#### How to use

1. The page loads with an input box labelled **"Transaction Description"**
2. Type or paste the description from your bank statement, e.g.
   - `Zomato food delivery payment`
   - `Uber cab to airport`
   - `BESCOM electricity bill ₹2300`
3. Click the **"🔍 Classify"** button

#### What you get back

- **Predicted Category** — one of the 10 categories (e.g. *Food & Dining*)
- **Confidence Score** as a percentage (e.g. *91.2 %*) with a plain-English label:
  - **Very High** (≥ 90 %) → trust this prediction
  - **High** (70–90 %) → likely correct
  - **Moderate** (50–70 %) → review before relying on it
  - **Low** (< 50 %) → the model is unsure; check manually
- **Bar chart** showing scores for all 10 categories — the model's full picture, not just the winner

#### The example buttons

Below the input box are **6 quick-fill example buttons** (Zomato, Uber, Netflix, Apollo, BESCOM, Amazon). Click any one to pre-fill the input — handy for first-time users who want to see what a prediction looks like before pasting their own data.

#### Submitting feedback

After a prediction appears, a small **feedback form** asks *"Was this prediction correct?"* You can:

- Click **Yes** — records that the model was right (helps measure accuracy)
- Pick the **correct category from the dropdown** and click *Submit Feedback* — records the correction

Every correction you submit is saved to a file (`feedback/feedback.jsonl`) on disk and feeds into the **drift detection** system: if too many corrections deviate from the training data distribution, the system automatically schedules a model retrain. *No manual action needed.*

---

### 5.2 Batch Prediction (Many at once)

**Use this when:** you have a whole bank statement, a CSV export, or a list of 10–500 transactions to categorise in one go.

Click **"Batch Predict"** in the left sidebar. You'll see **three tabs** at the top of the page — pick whichever matches your input format.

#### Tab 1 — 📁 Upload CSV

For when you have a CSV file (e.g. exported from a spreadsheet).

1. Prepare a CSV with **at least one column named `description`**. An `amount` column is optional and won't change classification but appears in the output.

   Example file content:
   ```
   description,amount
   Zomato payment,350
   Uber ride,120
   Netflix subscription,499
   ```
2. Click **Browse files** and select your CSV
3. A preview of the first 5 rows appears so you can confirm it parsed correctly
4. Click **🔍 Classify All**
5. Results appear within a few seconds:
   - **Table** with one row per input — `description`, `predicted_category`, `confidence`
   - **Donut chart** showing how your spending splits across the 10 categories
   - **Download Results CSV** button — saves a `results.csv` with the predictions appended as new columns

> **Limit:** 500 descriptions per upload. For larger files, split them into chunks.

#### Tab 2 — 📝 Paste Descriptions

For when you have a few descriptions copied from somewhere (email, message, screenshot OCR, etc.).

1. Paste your descriptions into the text area, **one per line**:
   ```
   Zomato delivery
   Uber to airport
   Netflix subscription
   Apollo pharmacy
   ```
2. Click **🔍 Classify All**
3. Same output as the CSV tab — table + donut chart + CSV download

This is the fastest tab for ad-hoc lists; no file preparation needed.

#### Tab 3 — 🏦 Bank Statement

**The most powerful option.** Upload your **bank statement directly in XLS format**, exactly as your bank gives it to you. SpendSense handles all the cleanup automatically.

1. Log in to your bank net banking → download your account statement → choose **XLS format** (not XLSX, not PDF)
2. In the SpendSense tab, click **Browse files** and upload the `.xls`
3. Click **🔍 Classify All**

What happens behind the scenes:
- The app finds the transaction table inside the XLS.
- **Filters to debit (withdrawal) transactions only** — your spending, not your salary credits
- **Strips bank-specific prefixes** automatically: `UPI/`, `NEFT/`, `RTGS/`, `IMPS/`, `POS `, `ATM `, etc. So `POS ZOMATO 9148` becomes `ZOMATO 9148` before classification — much cleaner input
- Classifies each cleaned narration

You get the same (as above) table + donut chart + CSV download.

---

### 5.3 Pipeline Status (System health)

**Use this when:** you want to see whether everything is running, navigate to internal tools (MLflow / Airflow / Grafana), or check recent pipeline runs.

Click **"⚙️ Pipeline Status"** in the sidebar.

#### Service Health grid (top of page)

A 7-cell grid showing each backend service. Icons mean:

| Icon | Meaning |
|---|---|
| ✅ | Service is **healthy** and responding |
| ⚠️ | Service is **slow** or returning intermittent errors |
| ❌ | Service is **unreachable** — see Troubleshooting |

The 7 services shown:
- **FastAPI Backend** — the prediction API (this must be ✅ for predictions to work)
- **MLflow** — keeps history of every model trained
- **Airflow** — runs the daily data pipeline
- **Prometheus** — collects performance metrics
- **Grafana** — visualises those metrics
- **Pushgateway** — receives metrics from background jobs
- **Alertmanager** — sends email alerts when alerts are fired

#### Live Metrics (middle of page)

Click **🔄 Refresh Metrics** to pull fresh numbers from Prometheus. You see:

- Total requests served
- Current error rate (should be 0–1 %)
- Average latency (should be under 50 ms)
- Predictions made per category

These are live counters — refresh after using the app to see them tick up.

#### DVC Pipeline diagram

A small flowchart showing the four ML stages: **ingest → preprocess → train → evaluate**. Useful for explaining the data flow to others.

#### Airflow DAG Run History

The most recent runs of the daily ingestion pipeline, each expandable to show all 9 task statuses (green = success, red = failure). If a recent run is red, click into it for the failure details.

#### Direct Links section (bottom)

One-click navigation to:
- MLflow (http://localhost:5000) — see every training run, parameters, metrics, confusion matrix
- Airflow (http://localhost:8080) — manually trigger the pipeline, see DAG graph
- Grafana (http://localhost:3001) — the live monitoring dashboard (covered next)
- Prometheus (http://localhost:9090) — raw metric query interface
- FastAPI Swagger (http://localhost:8000/docs) — interactive API documentation

---

## 6. Reading the Grafana Monitoring Dashboard

This section is the answer to **"Is SpendSense actually working well right now?"**

### Opening Grafana

> **http://localhost:3001**
>
> Username: `admin`  ·  Password: `admin`

After logging in, click **Dashboards** (left sidebar) → **SpendSense Overview**. You'll see **8 panels**, each showing a different aspect of the system. Read them like this:

### Panel 1 — Request Rate (req/s)

A timeseries line chart. Shows **how many predictions are being made per second**, broken down by which API endpoint is being called.

| What you see | What it means |
|---|---|
| Line at 0 | No traffic — nobody is using the app right now |
| Steady low line (1–5 req/s) | Normal interactive use (you on the Streamlit UI) |
| Sustained high line (50+ req/s) | Heavy batch predict jobs running |
| Sudden cliff to 0 | The backend just crashed — check Panel 2 |

> **Healthy state:** non-zero whenever you're using the app, zero otherwise.

### Panel 2 — Model Loaded

A green/red status indicator.

| Color | Meaning | Action |
|---|---|---|
| 🟢 Green (1) | Model is loaded and ready to serve predictions | Nothing — you're good |
| 🔴 Red (0) | Model not loaded **or** backend crashed | See Troubleshooting |

> **Critical:** if this is red, the API will return errors. The panel goes red within ~10 seconds of a backend crash, so it's a fast early warning.

### Panel 3 — Predictions by Category

A pie chart. Slice sizes show **the distribution of predicted categories** since the dashboard started tracking.

| What you see | What it means |
|---|---|
| Mostly Food + Transport + Shopping | Typical personal spending |
| One slice dominates 80 %+ | Either you tested the same example many times, or your data is genuinely skewed |
| Empty | Nobody has made a prediction yet — try one! |

> **Use this to:** quickly see what your spending mix looks like across your data.

### Panel 4 — Total Requests

A single big number. **Cumulative request count since the backend started.**

| What you see | What it means |
|---|---|
| Resets to 0 | Backend was restarted (data isn't lost — just this counter) |
| Climbs steadily | Normal use |
| Stays flat for hours | No one is using the app — possibly fine, possibly a backend hang |

### Panel 5 — Latency Percentiles (P50 / P95 / P99)

A timeseries with **three lines**, each measuring a different "slowness" guarantee:

| Line | What it means | Healthy value |
|---|---|---|
| **P50** (median) | Half of requests are faster than this | < 30 ms |
| **P95** (95th percentile) | 95 % of requests are faster than this | < 100 ms |
| **P99** (99th percentile) | 99 % of requests are faster than this | < 200 ms |

> **Quick check:** if P95 is consistently above **200 ms**, the system is slow and the `HighPredictionLatency` alert will fire. CPU-quantised inference normally keeps you well under that.

### Panel 6 — Airflow Drift Flag

A binary status panel (0 or 1). Set by the daily Airflow ingestion pipeline:

| Value | Meaning |
|---|---|
| **0** | Latest day's data looks like the training distribution — model is on solid ground |
| **1** | Detected a > 10 % shift in transaction category distribution — **time to retrain** |

When this flips to 1, the system automatically:
1. Merges new data with feedback corrections
2. Triggers GitHub Actions to retrain the model
3. Once retrained, the new model auto-promotes to the registry
4. After 75 seconds it resets the flag to 0 (one alert email per drift event, no spam)

> You don't have to do anything when this fires — the loop closes itself.

### Panel 7 — Alerts Fired by Name

A pie chart showing which alerts have fired most often during the dashboard's time range. Slice sizes proportional to fire count.

11 alerts watch the system; the most common ones to see here:
- `HighErrorRate` — error rate exceeded 5 % for 2 min
- `HighPredictionLatency` — P95 above 500 ms for 5 min
- `DataDriftDetected` — Panel 6 flipped to 1
- `ModelNotLoaded` — Panel 2 went red
- `LowTestF1` — most recent training produced a worse model than the gate (0.70)

> **Healthy state:** this panel is empty or shows only `DataDriftDetected` (which is expected during the demo, not a problem).

### Panel 8 — Recent Email Alerts

A table of all alerts currently firing — alert name, severity, instance, value. **Click a row to see the full alert detail in Alertmanager.**

> **Healthy state:** empty table.

### Quick "are we healthy?" routine

A 30-second sanity check, in this order:

1. **Panel 2 green?** ✅ → backend works
2. **Panel 5 P95 below 200 ms?** ✅ → fast enough
3. **Panel 8 empty?** ✅ → no active alerts
4. **Panel 1 has a non-zero line during recent use?** ✅ → traffic is being served

If all four are green, the system is healthy.

---

## 7. Stopping the Application

When you're done for the day:

```bash
docker compose down
```

This stops and removes all 8 containers but keeps your data, model, and feedback intact. Next time you run `docker compose up -d`, everything resumes where it left off.

If you want to **wipe all generated data** (start fresh — careful, this deletes feedback history):

```bash
docker compose down -v
```

---

## 8. Troubleshooting

| Problem | Most Likely Cause | Fix |
|---|---|---|
| Streamlit page won't load (browser timeout) | Frontend container not started | `docker compose up -d frontend` |
| Streamlit loads but says **"Cannot connect to backend"** | Backend not started, or model not loaded yet | Check `curl http://localhost:8000/ready` — if `false`, wait 30 s and retry. If still false, see the next row |
| `/ready` returns `false` indefinitely | `models/latest_model.pt` is missing | Run `dvc pull` or `dvc repro`, then `docker compose restart backend` |
| Page loads but **Pipeline Status** shows ❌ for FastAPI | Backend container crashed | `docker logs spendsense_backend --tail 50` to see error; usually `docker compose restart backend` fixes it |
| Predictions return **"Internal Server Error"** | Backend logs will tell you | `docker logs spendsense_backend --tail 30` |
| Bank statement upload returns **"No transactions found"** | File is XLSX, not XLS, or it's PDF | Re-download from HDFC net banking and pick **XLS** format |
| Confidence is consistently low (< 50 %) on all your inputs | Your input format differs greatly from training data | Try removing prefixes like "POS " or "UPI/" manually; SpendSense was trained on cleaned descriptions |
| Grafana shows "No data" on every panel | You just started the stack — Prometheus needs ~15 s to scrape first data | Wait 30 s and refresh Grafana |
| Grafana login fails with admin/admin | Someone changed the password earlier | `docker compose down -v && docker compose up -d` (deletes Grafana state and resets to defaults — won't affect predictions or model) |
| `docker compose ps` shows a container `Restarting` | Disk full, port conflict, or env var missing | `docker logs <container_name>` to see the actual error |
| All ports in use error on `docker compose up` | Another app (Jupyter, dev server) is using one of 5000/8000/8080/8501/9090/9091/9093/3001 | Find and stop the conflicting app, or change the port in `docker-compose.yml` |

If a problem persists, capture:
```bash
docker compose ps                         # which containers are up
docker compose logs --tail 50 > logs.txt  # recent logs from all services
```
and share `logs.txt` with the project maintainer.

---

## 9. Reference: The 10 Expense Categories

| Category | Typical Transactions |
|---|---|
| 🍽️ **Food & Dining** | Zomato, Swiggy, restaurants, groceries, cafes |
| 🚗 **Transportation** | Uber, Ola, petrol, bus pass, metro, parking |
| 🛍️ **Shopping & Retail** | Amazon, Flipkart, clothing, electronics |
| 🏥 **Healthcare & Medical** | Pharmacy, doctor fees, lab tests, diagnostic centres |
| 🎬 **Entertainment & Recreation** | Netflix, Spotify, BookMyShow, gaming, gym |
| 💡 **Utilities & Services** | Electricity, water, internet, gas, mobile recharge |
| 💳 **Financial Services** | Credit card payment, SIP, insurance premium, EMI |
| 🏛️ **Government & Legal** | Income tax, passport fees, court fees, RTO |
| 💵 **Income** | Salary, freelance payment, refunds, dividends |
| 🤝 **Charity & Donations** | NGO donation, temple donation, crowdfunding |

> The model returns probabilities across **all 10**, so even when the top guess is wrong you can usually find the right one in the bar chart's runner-up.

---

## Glossary

- **Backend** — the FastAPI application that runs the model and serves `/predict`
- **Frontend** — the Streamlit application you interact with in the browser
- **Drift** — when new data starts looking statistically different from the data the model was trained on (people's spending habits change, new merchants appear)
- **DVC** — Data Version Control; tracks data and model files in Git the same way Git tracks code
- **MLflow** — keeps a history of every model that was ever trained, including metrics and the model file itself
- **Airflow** — schedules and runs the daily data ingestion pipeline and checks for data drift
- **Prometheus / Grafana** — Prometheus collects performance numbers; Grafana draws charts from them
- **Pushgateway** — a place where one-shot jobs (like training runs) can deposit their metrics for Prometheus to pick up
- **Alertmanager** — decides what to do when an alert fires (e.g. send an email)
- **F1 score** — a measure of model quality between 0 and 1; closer to 1 is better. SpendSense's gate is 0.70, current value is 0.987

---
