"""SpendSense Streamlit Frontend — Home / Single Prediction Page."""

import os

import requests
import streamlit as st

from monitoring import push_ui_event

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

CATEGORY_ICONS = {
    "Food & Dining": "🍽️",
    "Transportation": "🚗",
    "Utilities & Services": "💡",
    "Entertainment & Recreation": "🎬",
    "Shopping & Retail": "🛍️",
    "Healthcare & Medical": "🏥",
    "Financial Services": "💳",
    "Income": "💵",
    "Government & Legal": "🏛️",
    "Charity & Donations": "🤝",
}

CATEGORIES = list(CATEGORY_ICONS.keys())

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
                    f1_str = f" | F1={f1:.4f}" if f1 is not None else ""
                    ts = r.get("start_time", "")[:19]
                    rname = r.get("run_name", "")
                    label = f"{r['run_id'][:8]}... [{rname}]{f1_str} | {ts}"
                    run_options[label] = r["run_id"]

                selected_label = st.selectbox(
                    "Choose MLflow Run",
                    options=list(run_options.keys()),
                    index=0,
                )
                selected_run_id = run_options[selected_label]

                if selected_run_id == current_run_id:
                    st.caption("✅ Active")

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

# Pop example text BEFORE the form so it's available as the default value
default_val = st.session_state.pop("example_input", "")

# Input form
with st.form("predict_form"):
    description = st.text_input(
        "Transaction Description",
        value=default_val,
        placeholder="e.g. Zomato payment ₹350",
        max_chars=500,
    )
    submitted = st.form_submit_button("🔍 Classify", use_container_width=True)

if "ui_predictions" not in st.session_state:
    st.session_state.ui_predictions = 0
if "ui_errors" not in st.session_state:
    st.session_state.ui_errors = 0
if "last_result" not in st.session_state:
    st.session_state.last_result = None

if submitted:
    if not description.strip():
        st.warning("Please enter a transaction description.")
        st.session_state.last_result = None
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
                st.session_state.last_result = {
                    "description": description,
                    "category": data["predicted_category"],
                    "confidence": data["confidence"],
                    "scores": data["all_scores"],
                }
                st.session_state.ui_predictions += 1
                push_ui_event(st.session_state.ui_predictions,
                              st.session_state.ui_errors, 0)
            except requests.exceptions.ConnectionError:
                st.session_state.ui_errors += 1
                push_ui_event(st.session_state.ui_predictions,
                              st.session_state.ui_errors, 0)
                st.error("Cannot connect to the backend. Make sure the API server is running.")
                st.session_state.last_result = None
            except requests.exceptions.HTTPError as e:
                st.session_state.ui_errors += 1
                push_ui_event(st.session_state.ui_predictions,
                              st.session_state.ui_errors, 0)
                st.error(f"API error: {e.response.json().get('detail', str(e))}")
                st.session_state.last_result = None
            except Exception as e:
                st.session_state.ui_errors += 1
                push_ui_event(st.session_state.ui_predictions,
                              st.session_state.ui_errors, 0)
                st.error(f"Unexpected error: {e}")
                st.session_state.last_result = None

# ── Show result + feedback UI ─────────────────────────────────────────────────
if st.session_state.last_result:
    result = st.session_state.last_result
    cat = result["category"]
    conf = result["confidence"]
    scores = result["scores"]
    icon = CATEGORY_ICONS.get(cat, "📂")

    st.success(f"### {icon} {cat}")
    st.metric("Confidence", f"{conf * 100:.1f}%")
    st.caption(
        "Confidence is the model's softmax probability for this category — "
        "how certain it is. Above 80% = high confidence; below 50% = the model "
        "sees multiple plausible categories."
    )
    st.divider()
    st.markdown("**Score Distribution**")
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    for cls, score in sorted_scores:
        ico = CATEGORY_ICONS.get(cls, "📂")
        st.progress(score, text=f"{ico} {cls}: {score * 100:.1f}%")

    # ── Feedback correction UI ────────────────────────────────────────────────
    st.divider()
    st.markdown("**Was this prediction wrong? Submit a correction:**")
    col_sel, col_btn = st.columns([3, 1])
    with col_sel:
        default_idx = CATEGORIES.index(cat) if cat in CATEGORIES else 0
        correct_cat = st.selectbox(
            "Correct Category",
            options=CATEGORIES,
            index=default_idx,
            key="feedback_category",
        )
    with col_btn:
        st.write("")
        if st.button("📝 Submit", use_container_width=True, key="feedback_submit"):
            try:
                fb_resp = requests.post(
                    f"{BACKEND_URL}/feedback",
                    json={
                        "description": result["description"],
                        "predicted_category": cat,
                        "actual_category": correct_cat,
                    },
                    timeout=5,
                )
                if fb_resp.status_code == 200:
                    st.success("✅ Correction recorded!")
                else:
                    st.error("Failed to record feedback.")
            except Exception as e:
                st.error(f"Error submitting feedback: {e}")

# ── Examples ──────────────────────────────────────────────────────────────────
st.divider()
st.markdown("**Try these examples** (click to populate the input above):")

examples = [
    "Arby's Contactless",
    "Occupational Therapy",
    "Potbelly Store Branch",
    "IRS Tax Refund",
    "Amazon Prime Renewal",
    "Electric Bill Payment",
]

cols = st.columns(3)
for i, ex in enumerate(examples):
    with cols[i % 3]:
        if st.button(ex, key=f"ex_{i}", use_container_width=True):
            st.session_state["example_input"] = ex
            st.rerun()
