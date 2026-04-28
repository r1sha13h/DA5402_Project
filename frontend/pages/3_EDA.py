"""SpendSense Streamlit Frontend — Exploratory Data Analysis Page."""

import json
import os

import altair as alt
import pandas as pd
import streamlit as st

DATA_DIR = os.environ.get(
    "DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data"),
)

ORIGINAL_ROWS = 4_500_000  # raw HuggingFace download before any cleanup

st.set_page_config(page_title="EDA — SpendSense", page_icon="📊", layout="wide")
st.title("📊 Exploratory Data Analysis")
st.markdown(
    "The original HuggingFace dataset had **4.5M rows**. After deduplication, null removal, "
    "and unknown-category filtering, **1.34M rows** were retained and split 90 / 10 for "
    "training and drift simulation."
)
st.divider()


@st.cache_data(show_spinner="Loading datasets…")
def load_data():
    base = pd.read_csv(
        os.path.join(DATA_DIR, "raw", "transactions_90.csv"),
        usecols=["description", "category"],
    )
    drift = pd.read_csv(
        os.path.join(DATA_DIR, "drift", "transactions_drift.csv"),
        usecols=["description", "category"],
    )
    stats_path = os.path.join(DATA_DIR, "ingested", "baseline_stats.json")
    with open(stats_path) as f:
        baseline_stats = json.load(f)
    return base, drift, baseline_stats


try:
    df_base, df_drift, stats = load_data()
except FileNotFoundError as e:
    st.error(f"Data files not found: {e}. Ensure the data volume is mounted correctly.")
    st.stop()

cleaned_rows = stats["total_rows"]
eliminated_rows = ORIGINAL_ROWS - cleaned_rows

# ── Section 1: Overview ────────────────────────────────────────────────────────
st.subheader("Dataset Overview")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Original dataset", f"{ORIGINAL_ROWS:,}")
c2.metric("After cleanup", f"{cleaned_rows:,}", delta=f"-{eliminated_rows:,} removed")
c3.metric("Baseline split (90%)", f"{len(df_base):,}")
c4.metric("Drift split (10%)", f"{len(df_drift):,}")

st.divider()

# ── Section 2: Cleanup Pie Chart ───────────────────────────────────────────────
st.subheader("Data Cleanup — 4.5M → 1.34M")
st.caption(
    "Rows eliminated during ingestion: nulls, unknown categories, and "
    "(description, category) duplicates."
)

pie_data = pd.DataFrame({
    "label": ["Retained after cleanup", "Removed (nulls / duplicates / unknown)"],
    "count": [cleaned_rows, eliminated_rows],
})

pie = (
    alt.Chart(pie_data)
    .mark_arc(outerRadius=130, innerRadius=55)
    .encode(
        theta=alt.Theta("count:Q"),
        color=alt.Color(
            "label:N",
            title="",
            scale=alt.Scale(range=["#4c9be8", "#e05252"]),
        ),
        tooltip=[
            "label:N",
            alt.Tooltip("count:Q", format=",", title="Rows"),
        ],
    )
    .properties(height=300)
)

text = (
    alt.Chart(pie_data)
    .mark_text(radius=170, fontSize=13)
    .encode(
        theta=alt.Theta("count:Q", stack=True),
        text=alt.Text("count:Q", format=","),
    )
)

st.altair_chart(pie + text, use_container_width=True)

st.divider()

# ── Section 3: Category Histograms ────────────────────────────────────────────
st.subheader("Category Distribution — Actual Counts")

base_counts = df_base["category"].value_counts().reset_index()
base_counts.columns = ["category", "count"]

drift_counts = df_drift["category"].value_counts().reset_index()
drift_counts.columns = ["category", "count"]

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Baseline split (90%)**")
    base_chart = (
        alt.Chart(base_counts)
        .mark_bar(color="#4c9be8")
        .encode(
            x=alt.X("category:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-35)),
            y=alt.Y("count:Q", title="Count"),
            tooltip=["category:N", alt.Tooltip("count:Q", format=",")],
        )
        .properties(height=320)
    )
    st.altair_chart(base_chart, use_container_width=True)

with col2:
    st.markdown("**Drift split (10%)**")
    drift_chart = (
        alt.Chart(drift_counts)
        .mark_bar(color="#e05252")
        .encode(
            x=alt.X("category:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-35)),
            y=alt.Y("count:Q", title="Count"),
            tooltip=["category:N", alt.Tooltip("count:Q", format=",")],
        )
        .properties(height=320)
    )
    st.altair_chart(drift_chart, use_container_width=True)

st.divider()

# ── Section 4: Drift Delta ─────────────────────────────────────────────────────
st.subheader("Drift Delta (Drift % − Baseline %)")
st.caption(
    "Positive (red) = over-represented in the drift split. "
    "Negative (blue) = under-represented. "
    "Dashed lines mark the ±10pp threshold that triggers the Airflow drift alert."
)

base_pct = df_base["category"].value_counts(normalize=True).mul(100).rename("base_pct")
drift_pct = df_drift["category"].value_counts(normalize=True).mul(100).rename("drift_pct")

delta = pd.concat([base_pct, drift_pct], axis=1).fillna(0)
delta["delta"] = delta["drift_pct"] - delta["base_pct"]
delta = delta.reset_index().rename(columns={"index": "category"})
delta = delta.sort_values("delta", ascending=False)

delta_chart = (
    alt.Chart(delta)
    .mark_bar()
    .encode(
        x=alt.X("category:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-35)),
        y=alt.Y("delta:Q", title="Δ Proportion (pp)"),
        color=alt.condition(
            alt.datum.delta > 0,
            alt.value("#e05252"),
            alt.value("#4c9be8"),
        ),
        tooltip=[
            "category:N",
            alt.Tooltip("base_pct:Q", format=".1f", title="Baseline %"),
            alt.Tooltip("drift_pct:Q", format=".1f", title="Drift %"),
            alt.Tooltip("delta:Q", format="+.1f", title="Delta (pp)"),
        ],
    )
    .properties(height=320)
)

thresholds = (
    alt.Chart(pd.DataFrame({"y": [10, -10]}))
    .mark_rule(strokeDash=[5, 3], color="orange", size=1.5)
    .encode(y="y:Q")
)

st.altair_chart(delta_chart + thresholds, use_container_width=True)

st.divider()

# ── Section 5: Description Length Distribution ─────────────────────────────────
st.subheader("Description Length Distribution")
st.caption(
    "Character length of transaction descriptions across both splits. "
    "Both splits should follow similar patterns if drift is category-only."
)

df_base["length"] = df_base["description"].str.len()
df_drift["length"] = df_drift["description"].str.len()

len_combined = pd.concat([
    df_base[["length"]].assign(split="Baseline (90%)").sample(
        min(20_000, len(df_base)), random_state=42
    ),
    df_drift[["length"]].assign(split="Drift (10%)").sample(
        min(20_000, len(df_drift)), random_state=42
    ),
])

len_chart = (
    alt.Chart(len_combined)
    .mark_bar(opacity=0.7)
    .encode(
        x=alt.X("length:Q", bin=alt.Bin(maxbins=40), title="Description length (chars)"),
        y=alt.Y("count()", title="Count", stack=None),
        color=alt.Color(
            "split:N",
            title="Split",
            scale=alt.Scale(range=["#4c9be8", "#e05252"]),
        ),
        tooltip=["split:N", "count()", alt.X("length:Q", bin=alt.Bin(maxbins=40))],
    )
    .properties(height=320)
)
st.altair_chart(len_chart, use_container_width=True)
