"""SpendSense Streamlit Frontend — Batch Prediction Page."""

import io
import os
import re
import sys

import altair as alt
import pandas as pd
import requests
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from monitoring import push_ui_event  # noqa: E402

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
BATCH_PROCESSED_DIR = os.environ.get(
    "BATCH_PROCESSED_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "batch", "batch_processed"),
)

st.set_page_config(page_title="Batch Predict — SpendSense", page_icon="📋", layout="wide")

st.title("📋 Batch Transaction Classifier")
st.markdown(
    "Upload a CSV or bank statement XLS to classify all transactions at once."
)

st.divider()

if "ui_batch_items" not in st.session_state:
    st.session_state.ui_batch_items = 0
if "ui_errors" not in st.session_state:
    st.session_state.ui_errors = 0


def _classify_descriptions(descriptions: list) -> list:
    """Send batch predict request and return results list."""
    resp = requests.post(
        f"{BACKEND_URL}/predict/batch",
        json={"descriptions": descriptions},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["results"]


def _clean_hdfc_narration(narration: str) -> str:
    """Strip HDFC transaction-code prefixes so the model sees natural language.

    HDFC narrations look like "UPI/ZOMATO/9148/FoodOrder" or "NEFT/SALARY/JOHN".
    The BiLSTM was trained on clean descriptions; removing these prefixes improves
    category accuracy substantially.
    """
    s = str(narration).strip()
    # Remove leading transaction type code and the slash/space after it
    s = re.sub(
        r'^(UPI|NEFT|RTGS|IMPS|ACH|ECS|SI|POS|ATM|CLG|BIL|NACH|NACH D-|DR|TO)\s*/?\s*',
        '', s, flags=re.IGNORECASE,
    )
    # Remove bare reference numbers that got left at the front (e.g. "123456789 SUPERMART")
    s = re.sub(r'^\d[\d/]*\s*', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s if s else narration  # keep original if cleaning leaves nothing


def _process_hdfc_xls(file_obj) -> pd.DataFrame:
    """Auto-detect header row in HDFC bank statement XLS and return (description, amount)."""
    raw = pd.read_excel(file_obj, header=None, engine="xlrd", dtype=str)

    header_row_idx = None
    for idx, row in raw.iterrows():
        row_vals = [str(v).strip().lower() for v in row if pd.notna(v) and str(v).strip()]
        if "narration" in row_vals:
            header_row_idx = idx
            break

    if header_row_idx is None:
        raise ValueError("Could not find a 'Narration' column header in the uploaded file.")

    # Seek back to 0 because xlrd consumed the stream; re-read with the correct header row
    file_obj.seek(0)
    df = pd.read_excel(file_obj, header=header_row_idx, engine="xlrd", dtype=str)

    narration_col = next(
        (c for c in df.columns if str(c).strip().lower() == "narration"), None
    )
    withdrawal_col = next(
        (c for c in df.columns if "withdrawal" in str(c).strip().lower()), None
    )
    date_col = next(
        (c for c in df.columns if str(c).strip().lower() == "date"), None
    )

    if not narration_col:
        raise ValueError(f"'Narration' column not found. Columns present: {list(df.columns)}")
    if not withdrawal_col:
        raise ValueError(
            f"'Withdrawal Amt.' column not found. Columns present: {list(df.columns)}"
        )

    # Filter to rows with a valid date — drops the bank's summary/footer rows
    check_col = date_col if date_col else df.columns[0]
    date_mask = df[check_col].astype(str).str.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
    df = df[date_mask].copy()

    # Keep only debit (withdrawal) rows
    df = df[df[withdrawal_col].notna()]
    df = df[~df[withdrawal_col].astype(str).str.strip().isin(["", "nan", "NaN"])]

    result = pd.DataFrame({
        "description": df[narration_col].astype(str).str.strip().apply(_clean_hdfc_narration),
        "amount": pd.to_numeric(df[withdrawal_col], errors="coerce"),
    })
    result = result.dropna(subset=["amount"])
    result = result[result["description"].str.strip() != ""]
    return result.reset_index(drop=True)


upload_tab, paste_tab, xls_tab = st.tabs([
    "📁 Upload CSV", "📝 Paste Descriptions", "🏦 Bank Statement (XLS)"
])

# ── Tab 1: CSV upload ─────────────────────────────────────────────────────────
with upload_tab:
    uploaded = st.file_uploader(
        "Upload CSV file", type=["csv"], help="Must contain a 'description' column."
    )

    if uploaded:
        try:
            df = pd.read_csv(uploaded)
        except Exception as e:
            st.error(f"Could not parse CSV: {e}")
            st.stop()

        if "description" not in df.columns:
            st.error("CSV must contain a `description` column.")
            st.stop()

        st.write(f"**{len(df)} rows loaded.** Preview:")
        st.dataframe(df.head(10), use_container_width=True)

        if st.button("🔍 Classify All", key="csv_btn", use_container_width=True):
            descriptions = df["description"].fillna("").tolist()
            with st.spinner(f"Classifying {len(descriptions)} transactions..."):
                try:
                    data = _classify_descriptions(descriptions)
                    result_df = pd.DataFrame([
                        {
                            "description": r["description"],
                            "predicted_category": r["predicted_category"],
                            "confidence": f"{r['confidence'] * 100:.1f}%",
                        }
                        for r in data
                    ])
                    if "amount" in df.columns:
                        result_df.insert(1, "amount", df["amount"].values)

                    st.success(f"✅ Classified {len(result_df)} transactions.")
                    st.dataframe(result_df, use_container_width=True)

                    st.divider()
                    st.markdown("**Category Distribution**")
                    cat_counts = result_df["predicted_category"].value_counts().reset_index()
                    cat_counts.columns = ["Category", "Count"]
                    st.bar_chart(cat_counts.set_index("Category"))

                    csv_bytes = result_df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "⬇️ Download Results CSV",
                        data=csv_bytes,
                        file_name="spendsense_predictions.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                    st.session_state.ui_batch_items += len(result_df)
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                except requests.exceptions.ConnectionError:
                    st.session_state.ui_errors += 1
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                    st.error("Cannot connect to the backend.")
                except requests.exceptions.HTTPError as e:
                    st.session_state.ui_errors += 1
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                    st.error(f"API error: {e.response.json().get('detail', str(e))}")
                except Exception as e:
                    st.session_state.ui_errors += 1
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                    st.error(f"Unexpected error: {e}")

# ── Tab 2: Paste descriptions ─────────────────────────────────────────────────
with paste_tab:
    st.markdown("Enter one transaction description per line:")
    text_input = st.text_area(
        "Descriptions",
        height=200,
        placeholder="Zomato food delivery\nUber ride\nNetflix subscription",
    )

    if st.button("🔍 Classify All", key="paste_btn", use_container_width=True):
        lines = [ln.strip() for ln in text_input.strip().splitlines() if ln.strip()]
        if not lines:
            st.warning("Please enter at least one description.")
        else:
            with st.spinner(f"Classifying {len(lines)} transactions..."):
                try:
                    data = _classify_descriptions(lines)
                    paste_df = pd.DataFrame([
                        {
                            "Description": r["description"],
                            "Category": r["predicted_category"],
                            "Confidence": f"{r['confidence'] * 100:.1f}%",
                        }
                        for r in data
                    ])
                    st.dataframe(paste_df, use_container_width=True)

                    csv_bytes = paste_df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "⬇️ Download Results CSV",
                        data=csv_bytes,
                        file_name="spendsense_paste_predictions.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                    st.session_state.ui_batch_items += len(data)
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                except requests.exceptions.ConnectionError:
                    st.session_state.ui_errors += 1
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                    st.error("Cannot connect to the backend.")
                except Exception as e:
                    st.session_state.ui_errors += 1
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                    st.error(f"Error: {e}")

# ── Tab 3: HDFC Bank Statement XLS ───────────────────────────────────────────
with xls_tab:
    st.markdown(
        "Upload your **HDFC Bank statement** (`.xls` export). "
        "The file should contain **Narration** and **Withdrawal Amt.** columns. "
        "Only debit (withdrawal) transactions will be classified."
    )
    xls_file = st.file_uploader(
        "Upload Bank Statement",
        type=["xls"],
        key="xls_uploader",
        help="HDFC bank statement exported as .xls",
    )

    if xls_file:
        with st.spinner("Parsing bank statement..."):
            try:
                txn_df = _process_hdfc_xls(xls_file)
            except Exception as e:
                st.error(f"Failed to parse bank statement: {e}")
                st.stop()

        st.success(f"✅ Found **{len(txn_df)} withdrawal transactions**. Preview:")
        st.dataframe(txn_df.head(10), use_container_width=True)

        if st.button("🔍 Classify Transactions", key="xls_btn", use_container_width=True):
            with st.spinner(f"Classifying {len(txn_df)} transactions..."):
                try:
                    data = _classify_descriptions(txn_df["description"].tolist())
                    result_df = pd.DataFrame([
                        {
                            "description": r["description"],
                            "amount": txn_df.loc[i, "amount"],
                            "predicted_category": r["predicted_category"],
                            "confidence": f"{r['confidence'] * 100:.1f}%",
                        }
                        for i, r in enumerate(data)
                    ])

                    # Save to disk
                    os.makedirs(BATCH_PROCESSED_DIR, exist_ok=True)
                    out_path = os.path.join(BATCH_PROCESSED_DIR, "predictions.csv")
                    result_df.to_csv(out_path, index=False)

                    st.success(f"✅ Classified {len(result_df)} transactions.")
                    st.dataframe(result_df, use_container_width=True)

                    # ── Spending breakdown chart ──────────────────────────────
                    st.divider()
                    st.markdown("### 💰 Spending Breakdown by Category")

                    agg = (
                        result_df.groupby("predicted_category")["amount"]
                        .sum()
                        .reset_index()
                    )
                    agg.columns = ["Category", "Amount"]
                    total_spent = agg["Amount"].sum()
                    agg["Percentage"] = (agg["Amount"] / total_spent * 100).round(1)

                    pie = (
                        alt.Chart(agg)
                        .mark_arc(innerRadius=50)
                        .encode(
                            theta=alt.Theta("Amount:Q"),
                            color=alt.Color(
                                "Category:N",
                                scale=alt.Scale(scheme="category20"),
                            ),
                            tooltip=[
                                alt.Tooltip("Category:N"),
                                alt.Tooltip("Amount:Q", format=",.2f", title="Amount (₹)"),
                                alt.Tooltip("Percentage:Q", format=".1f", title="%"),
                            ],
                        )
                        .properties(title="Spending by Category", width=380, height=300)
                    )
                    st.altair_chart(pie, use_container_width=True)

                    # ── Summary table ─────────────────────────────────────────
                    summary = agg.sort_values("Amount", ascending=False).copy()
                    summary["Amount (₹)"] = summary["Amount"].map("{:,.2f}".format)
                    summary["% of Total"] = summary["Percentage"].map("{:.1f}%".format)
                    st.markdown("**Category Summary**")
                    st.dataframe(
                        summary[["Category", "Amount (₹)", "% of Total"]],
                        use_container_width=True,
                        hide_index=True,
                    )

                    # ── Download ──────────────────────────────────────────────
                    csv_bytes = result_df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "⬇️ Download Classified Transactions",
                        data=csv_bytes,
                        file_name="hdfc_classified.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                    st.session_state.ui_batch_items += len(result_df)
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                except requests.exceptions.ConnectionError:
                    st.session_state.ui_errors += 1
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                    st.error("Cannot connect to the backend.")
                except Exception as e:
                    st.session_state.ui_errors += 1
                    push_ui_event(0, st.session_state.ui_errors,
                                  st.session_state.ui_batch_items)
                    st.error(f"Unexpected error: {e}")
