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
   - A **confidence score** (e.g., 91.2%)
   - A bar chart showing scores for all 10 categories

### Try the examples
Below the form, there are six example transactions. Click any of them to pre-fill the input.

---

## Page 2 — Batch Predict

### What it does
Classifies many transactions at once. Useful for processing a whole month's statement.

### Option A — Upload a CSV file

1. Click **"📁 Upload CSV"** tab.
2. Prepare a CSV file with at least one column called `description`.
   - Optionally include an `amount` column.
   - Example CSV:
     ```
     description,amount
     Zomato payment,350
     Uber ride,120
     Netflix subscription,499
     ```
3. Click **"Browse files"** and select your CSV.
4. A preview of the first 10 rows appears.
5. Click **"🔍 Classify All"**.
6. Results appear in a table with a category and confidence for each row.
7. A bar chart shows how your spending is distributed.
8. Click **"⬇️ Download Results CSV"** to save the predictions.

### Option B — Paste descriptions

1. Click **"📝 Paste Descriptions"** tab.
2. Type or paste one transaction description per line.
3. Click **"🔍 Classify All"**.
4. Results appear immediately in a table.

---

## Page 3 — Pipeline Status

### What it does
Shows the health and status of all backend services in real time.

### How to use it

1. Click **"⚙️ Pipeline Status"** in the sidebar.
2. You will see four status indicators:
   - **FastAPI Backend** — the model API
   - **MLflow Tracking** — the experiment tracker
   - **Airflow Webserver** — the data pipeline scheduler
   - **Grafana Dashboard** — the monitoring dashboard
3. Coloured boxes show whether each service is online (✅), has an issue (⚠️), or is unreachable (❌).
4. Click **"🔄 Refresh Metrics"** to see live request counts and error rates from Prometheus.
5. Scroll down to see links to the MLflow UI, Airflow UI, and Grafana dashboard.

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
| � Financial Services | Credit card payment, SIP, insurance premium |
| 💵 Income | Salary, freelance payment, refund |
| �️ Government & Legal | Tax payment, passport fees, court fees |
| 🤝 Charity & Donations | NGO donation, temple donation |

---

## Tips for Best Results

- Use the actual description text from your bank statement (copy-paste works best).
- Descriptions with brand names like "Zomato", "Uber", "Netflix" get the highest confidence.
- Very short descriptions (one word) may have lower confidence.
- If the confidence is below 50%, the prediction may be less reliable — use your judgement.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| "Cannot connect to backend" | Make sure the system administrator has started the services (`docker compose up`) |
| Page loads but shows ❌ for backend | Wait a minute for the model to finish loading, then refresh |
| Low confidence scores | Try a more descriptive input (add the merchant name) |
| CSV upload fails | Make sure your file has a column exactly named `description` |
| Results seem wrong | This is a neural network — occasional misclassifications are expected |

---

## Contact & Support

For technical issues, contact the project team or raise an issue on the GitHub repository.
