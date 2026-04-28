"""SpendSense Streamlit Frontend — Exploratory Data Analysis Page."""

import os

import altair as alt
import pandas as pd
import streamlit as st

DATA_DIR = os.environ.get(
    "DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data"),
)

st.set_page_config(page_title="EDA — SpendSense", page_icon="📊", layout="wide")
st.title("📊 Exploratory Data Analysis")
st.markdown(
    "Comparing the **90% baseline** training split against the **10% drift** split "
    "to understand data distribution and the intentional skew introduced for drift detection."
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
    return base, drift


try:
    df_base, df_drift = load_data()
except FileNotFoundError as e:
    st.error(f"Data files not found: {e}. Ensure the data volume is mounted correctly.")
    st.stop()

# ── Section 1: Overview ────────────────────────────────────────────────────────
st.subheader("Dataset Overview")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Baseline rows", f"{len(df_base):,}")
c2.metric("Drift rows", f"{len(df_drift):,}")
c3.metric("Categories (baseline)", df_base["category"].nunique())
c4.metric("Categories (drift)", df_drift["category"].nunique())

st.divider()

# ── Section 2: Category Distribution ──────────────────────────────────────────
st.subheader("Category Distribution")
st.caption(
    "Proportion of each category in each split. "
    "The drift split intentionally over-samples the top-3 categories to guarantee a >10pp shift."
)

base_dist = (
    df_base["category"]
    .value_counts(normalize=True)
    .mul(100)
    .reset_index()
    .rename(columns={"proportion": "pct", "category": "category"})
)
base_dist.columns = ["category", "pct"]
base_dist["split"] = "Baseline (90%)"

drift_dist = (
    df_drift["category"]
    .value_counts(normalize=True)
    .mul(100)
    .reset_index()
    .rename(columns={"proportion": "pct", "category": "category"})
)
drift_dist.columns = ["category", "pct"]
drift_dist["split"] = "Drift (10%)"

combined = pd.concat([base_dist, drift_dist])

dist_chart = (
    alt.Chart(combined)
    .mark_bar()
    .encode(
        x=alt.X("category:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-30)),
        y=alt.Y("pct:Q", title="Proportion (%)"),
        color=alt.Color("split:N", title="Split"),
        xOffset="split:N",
        tooltip=["category:N", "split:N", alt.Tooltip("pct:Q", format=".1f", title="Pct %")],
    )
    .properties(height=350)
)
st.altair_chart(dist_chart, use_container_width=True)

st.divider()

# ── Section 3: Drift Delta ─────────────────────────────────────────────────────
st.subheader("Drift Delta (Drift % − Baseline %)")
st.caption(
    "Positive = over-represented in drift split (red). "
    "Negative = under-represented (blue). "
    "Anything beyond ±10pp triggers the Airflow drift alert."
)

delta = base_dist.set_index("category")[["pct"]].join(
    drift_dist.set_index("category")[["pct"]], lsuffix="_base", rsuffix="_drift"
)
delta["delta"] = delta["pct_drift"] - delta["pct_base"]
delta = delta.reset_index().sort_values("delta", ascending=False)

delta_chart = (
    alt.Chart(delta)
    .mark_bar()
    .encode(
        x=alt.X("category:N", sort="-y", title=None, axis=alt.Axis(labelAngle=-30)),
        y=alt.Y("delta:Q", title="Δ Proportion (pp)"),
        color=alt.condition(
            alt.datum.delta > 0,
            alt.value("#e05252"),
            alt.value("#5b9bd5"),
        ),
        tooltip=[
            "category:N",
            alt.Tooltip("pct_base:Q", format=".1f", title="Baseline %"),
            alt.Tooltip("pct_drift:Q", format=".1f", title="Drift %"),
            alt.Tooltip("delta:Q", format="+.1f", title="Delta (pp)"),
        ],
    )
    .properties(height=300)
)

# 10pp threshold reference lines
rule = (
    alt.Chart(pd.DataFrame({"y": [10, -10]}))
    .mark_rule(strokeDash=[4, 4], color="orange", size=1.5)
    .encode(y="y:Q")
)
st.altair_chart(delta_chart + rule, use_container_width=True)

st.divider()

# ── Section 4: Description Length ─────────────────────────────────────────────
st.subheader("Description Length Distribution")
st.caption(
    "Character length of transaction descriptions. "
    "Both splits should have similar patterns if drift is category-only (not description-level)."
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
        color=alt.Color("split:N", title="Split"),
        tooltip=["split:N", "count()"],
    )
    .properties(height=300)
)
st.altair_chart(len_chart, use_container_width=True)

st.divider()

# ── Section 5: Data Quality ────────────────────────────────────────────────────
st.subheader("Data Quality")

c1, c2 = st.columns(2)
with c1:
    st.markdown("**Baseline — null counts**")
    nulls_base = df_base[["description", "category"]].isnull().sum().reset_index()
    nulls_base.columns = ["Column", "Nulls"]
    st.dataframe(nulls_base, hide_index=True, use_container_width=True)

with c2:
    st.markdown("**Drift — null counts**")
    nulls_drift = df_drift[["description", "category"]].isnull().sum().reset_index()
    nulls_drift.columns = ["Column", "Nulls"]
    st.dataframe(nulls_drift, hide_index=True, use_container_width=True)
