# User Manual — SpendSense

## What is SpendSense?

SpendSense is a smart expense categoriser. You paste or upload your bank transaction descriptions (like "Zomato payment ₹350" or "BESCOM electricity bill") and SpendSense automatically tells you which spending category they belong to — Food & Dining, Transport, Utilities, and seven more.

No technical knowledge is required to use SpendSense.

---

## How to Access SpendSense

Open your web browser and go to:

```
http://localhost:8501
```

You will see the SpendSense home page.

---

## Page 1 — Home (Single Prediction)

### What it does
Classifies one transaction description at a time.

### How to use it

1. Type or paste your transaction description in the box labelled **"Transaction Description"**.
   - Example: `Zomato food delivery payment`
   - Example: `Uber cab to airport`
   - Example: `Apollo pharmacy medicines`

2. Click the **"🔍 Classify"** button.

3. The result appears instantly:
   - The predicted **category** (e.g., Food & Dining)
   - A **confidence score** (e.g., 91.2%) with a plain-English explanation of what the score means
   - A bar chart showing scores for all 10 categories

### Try the examples
Below the input box, there are six example transactions. Click any of them to pre-fill the input box, then click **Classify** to see the prediction.

### Give feedback
After a prediction appears, a feedback section asks: "Was this prediction correct?" You can select the correct category if the model got it wrong. Your feedback helps improve the model over time.

---

## Page 2 — Batch Predict

### What it does
Classifies many transactions at once. Useful for processing a whole month's statement.

### Option A — Upload a CSV file

1. Click the **"📁 Upload CSV"** tab.
2. Prepare a CSV file with at least one column called `description`.
   - Optionally include an `amount` column.
   - Example:
     ```
     description,amount
     Zomato payment,350
     Uber ride,120
     Netflix subscription,499
     ```
3. Click **"Browse files"** and select your CSV.
4. A preview of the first few rows appears.
5. Click **"🔍 Classify All"**.
6. Results appear in a table with a category and confidence for each row.
7. A donut chart shows how your spending is distributed.
8. Click **"⬇️ Download Results CSV"** to save the predictions.

### Option B — Paste descriptions

1. Click the **"📝 Paste Descriptions"** tab.
2. Type or paste one transaction description per line.
3. Click **"🔍 Classify All"**.
4. Results appear immediately in a table.

### Option C — Upload an HDFC bank statement (XLS)

1. Click the **"🏦 HDFC Statement"** tab.
2. Download your HDFC account statement in XLS format from your bank's net banking portal.
3. Click **"Browse files"** and upload the XLS file.
4. SpendSense automatically finds the transaction table, filters to debit (withdrawal) transactions, and strips bank-specific prefixes (UPI/, NEFT/, POS, etc.) from narrations before classification.
5. Results appear in a table with predicted categories.

---

## Page 3 — Pipeline Status

### What it does
Shows the health and status of all backend services in real time, and provides access to all monitoring and tracking tools.

### How to use it

1. Click **"⚙️ Pipeline Status"** in the sidebar.
2. The **Service Health** grid shows whether each service is online (✅), has an issue (⚠️), or is unreachable (❌):
   - **FastAPI Backend** — the model API
   - **MLflow** — the experiment tracker
   - **Airflow** — the data pipeline scheduler
   - **Prometheus** — the metrics collector
   - **Grafana** — the monitoring dashboard
   - **Pushgateway** — the metrics receiver
   - **Alertmanager** — the alert router
3. Click **"🔄 Refresh Metrics"** to see live request counts, error rates, and other counters from Prometheus.
4. The **DVC Pipeline DAG** section shows the ML pipeline stages as a diagram.
5. The **Airflow DAG Run History** section shows recent pipeline runs with the status of each task.
6. Scroll down for direct links to the MLflow UI, Airflow UI, Grafana dashboard, and other tools.

---

## The 10 Expense Categories

| Category | Typical Transactions |
|---|---|
| 🍽️ Food & Dining | Zomato, Swiggy, restaurants, groceries |
| 🚗 Transportation | Uber, Ola, petrol, bus pass, metro |
| 💡 Utilities & Services | Electricity, water, internet, gas, mobile recharge |
| 🎬 Entertainment & Recreation | Netflix, Spotify, cinema, gaming |
| 🛍️ Shopping & Retail | Amazon, Flipkart, clothing stores |
| 🏥 Healthcare & Medical | Pharmacy, doctor fees, diagnostic tests |
| 💳 Financial Services | Credit card payment, SIP, insurance premium |
| 💵 Income | Salary, freelance payment, refund |
| 🏛️ Government & Legal | Tax payment, passport fees, court fees |
| 🤝 Charity & Donations | NGO donation, temple donation |

---

## Tips for Best Results

- Use the actual description text from your bank statement (copy-paste works best).
- Descriptions with brand names like "Zomato", "Uber", "Netflix" get the highest confidence.
- Very short descriptions (one word) may have lower confidence.
- If the confidence is below 50%, the prediction may be less reliable — use your judgement.
- For HDFC statements: use the XLS format downloaded directly from HDFC net banking. The app handles the prefix stripping automatically.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| "Cannot connect to backend" | Make sure the system administrator has started the services (`docker compose up`) |
| Page loads but shows ❌ for backend | Wait a minute for the model to finish loading, then refresh |
| Low confidence scores | Try a more descriptive input (add the merchant name) |
| CSV upload fails | Make sure your file has a column exactly named `description` |
| HDFC XLS upload shows no results | Ensure the file is in XLS (not XLSX) format from HDFC net banking |
| Results seem wrong | This is a neural network — occasional misclassifications are expected. Use the feedback form to report corrections |

---

## Contact & Support

For technical issues, contact the project team or raise an issue on the GitHub repository.
