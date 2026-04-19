"""SpendSense Streamlit Frontend — Home / Single Prediction Page."""

import os

import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

CATEGORY_ICONS = {
    "Food & Dining": "🍽️",
    "Transportation": "🚗",
    "Utilities & Services": "💡",
    "Entertainment & Recreation": "🎬",
    "Shopping & Retail": "🛍️",
    "Healthcare & Medical": "🏥",
    "Financial Services": "�",
    "Income": "💵",
    "Government & Legal": "�️",
    "Charity & Donations": "🤝",
}

st.set_page_config(
    page_title="SpendSense",
    page_icon="💸",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/money.png", width=64)
    st.title("SpendSense")
    st.caption("Personal Expense Category Classifier")
    st.divider()
    st.markdown("**Navigation**")
    st.page_link("Home.py", label="🏠 Home — Predict")
    st.page_link("pages/1_Batch_Predict.py", label="📋 Batch Predict")
    st.page_link("pages/2_Pipeline_Status.py", label="⚙️ Pipeline Status")
    st.divider()
    st.caption(f"Backend: `{BACKEND_URL}`")

    # Model readiness indicator
    try:
        resp = requests.get(f"{BACKEND_URL}/ready", timeout=2)
        if resp.status_code == 200:
            ready_data = resp.json()
            st.success("✅ Model ready")
            if ready_data.get("message"):
                st.caption(ready_data["message"])
        else:
            st.warning("⚠️ Model loading...")
    except requests.exceptions.RequestException:
        st.error("❌ Backend unreachable")

    # ── Model Selection ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("**🔀 Model Selection**")
    try:
        models_resp = requests.get(f"{BACKEND_URL}/models", timeout=5)
        if models_resp.status_code == 200:
            models_data = models_resp.json()
            runs = models_data.get("runs", [])
            current_run_id = models_data.get("current_run_id")

            if runs:
                run_options = {}
                for r in runs:
                    f1 = r.get("best_val_f1")
                    f1_str = f" | F1={f1:.4f}" if f1 else ""
                    ts = r.get("start_time", "")[:19]
                    label = f"{r['run_id'][:8]}...{f1_str} | {ts}"
                    run_options[label] = r["run_id"]

                selected_label = st.selectbox(
                    "Choose MLflow Run",
                    options=list(run_options.keys()),
                    index=0,
                )
                selected_run_id = run_options[selected_label]

                active_marker = "✅ Active" if selected_run_id == current_run_id else ""
                if active_marker:
                    st.caption(active_marker)

                if st.button("🚀 Load this model", use_container_width=True):
                    with st.spinner("Switching model..."):
                        switch_resp = requests.post(
                            f"{BACKEND_URL}/models/switch",
                            json={"run_id": selected_run_id},
                            timeout=30,
                        )
                        if switch_resp.status_code == 200:
                            st.success(f"Model switched to `{selected_run_id[:8]}...`")
                            st.rerun()
                        else:
                            detail = switch_resp.json().get("detail", "Unknown error")
                            st.error(f"Switch failed: {detail}")
            else:
                st.info("No MLflow runs found yet.")
        else:
            st.warning("Could not fetch model list.")
    except requests.exceptions.RequestException:
        st.caption("⚠️ MLflow unavailable — using disk model.")

# ── Main content ──────────────────────────────────────────────────────────────
st.title("💸 SpendSense")
st.subheader("Intelligent Transaction Classifier")
st.markdown(
    "Paste any bank transaction description below and SpendSense will "
    "automatically categorise it using a trained **Bidirectional LSTM** model."
)

st.divider()

# Input form
with st.form("predict_form"):
    description = st.text_input(
        "Transaction Description",
        placeholder="e.g. Zomato payment ₹350",
        max_chars=500,
    )
    submitted = st.form_submit_button("🔍 Classify", use_container_width=True)

if submitted:
    if not description.strip():
        st.warning("Please enter a transaction description.")
    else:
        with st.spinner("Classifying..."):
            try:
                resp = requests.post(
                    f"{BACKEND_URL}/predict",
                    json={"description": description},
                    timeout=5,
                )
                resp.raise_for_status()
                data = resp.json()

                cat = data["predicted_category"]
                conf = data["confidence"]
                scores = data["all_scores"]
                icon = CATEGORY_ICONS.get(cat, "📂")

                st.success(f"### {icon} {cat}")
                st.metric("Confidence", f"{conf * 100:.1f}%")
                st.divider()
                st.markdown("**Score Distribution**")

                sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                for cls, score in sorted_scores:
                    ico = CATEGORY_ICONS.get(cls, "📂")
                    st.progress(
                        score,
                        text=f"{ico} {cls}: {score * 100:.1f}%",
                    )

            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to the backend. Make sure the API server is running.")
            except requests.exceptions.HTTPError as e:
                st.error(f"API error: {e.response.json().get('detail', str(e))}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")

# ── Examples ──────────────────────────────────────────────────────────────────
st.divider()
st.markdown("**Try these examples:**")

examples = [
    "Zomato food delivery payment",
    "BESCOM electricity bill payment",
    "Uber ride to airport",
    "Netflix monthly subscription",
    "Apollo pharmacy medicines",
    "Amazon order #1234",
]

cols = st.columns(3)
for i, ex in enumerate(examples):
    with cols[i % 3]:
        if st.button(ex, key=f"ex_{i}", use_container_width=True):
            st.session_state["example_input"] = ex
            st.rerun()

if "example_input" in st.session_state:
    st.info(f"**Copied:** {st.session_state['example_input']} — paste it above and classify!")
    del st.session_state["example_input"]
