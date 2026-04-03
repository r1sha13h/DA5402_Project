"""SpendSense Streamlit Frontend — Batch Prediction Page."""

import io
import os

import pandas as pd
import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Batch Predict — SpendSense", page_icon="📋", layout="wide")

st.title("📋 Batch Transaction Classifier")
st.markdown(
    "Upload a CSV file with a `description` column (and optionally an `amount` column) "
    "to classify all transactions at once."
)

st.divider()

upload_tab, paste_tab = st.tabs(["📁 Upload CSV", "📝 Paste Descriptions"])

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
                    resp = requests.post(
                        f"{BACKEND_URL}/predict/batch",
                        json={"descriptions": descriptions},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    data = resp.json()["results"]
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

                    # Category summary
                    st.divider()
                    st.markdown("**Category Distribution**")
                    cat_counts = result_df["predicted_category"].value_counts().reset_index()
                    cat_counts.columns = ["Category", "Count"]
                    st.bar_chart(cat_counts.set_index("Category"))

                    # Download
                    csv_bytes = result_df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "⬇️ Download Results CSV",
                        data=csv_bytes,
                        file_name="spendsense_predictions.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                except requests.exceptions.ConnectionError:
                    st.error("Cannot connect to the backend.")
                except requests.exceptions.HTTPError as e:
                    st.error(f"API error: {e.response.json().get('detail', str(e))}")
                except Exception as e:
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
        lines = [l.strip() for l in text_input.strip().splitlines() if l.strip()]
        if not lines:
            st.warning("Please enter at least one description.")
        else:
            with st.spinner(f"Classifying {len(lines)} transactions..."):
                try:
                    resp = requests.post(
                        f"{BACKEND_URL}/predict/batch",
                        json={"descriptions": lines},
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json()["results"]
                    st.dataframe(
                        pd.DataFrame([
                            {
                                "Description": r["description"],
                                "Category": r["predicted_category"],
                                "Confidence": f"{r['confidence'] * 100:.1f}%",
                            }
                            for r in data
                        ]),
                        use_container_width=True,
                    )
                except requests.exceptions.ConnectionError:
                    st.error("Cannot connect to the backend.")
                except Exception as e:
                    st.error(f"Error: {e}")
