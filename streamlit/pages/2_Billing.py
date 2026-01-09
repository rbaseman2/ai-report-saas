import os
import requests
import streamlit as st
import streamlit.components.v1 as components

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

st.set_page_config(page_title="Billing & Subscription", layout="wide")

# ---------------------------------------------------------
# Read query params (Stripe redirect lands here)
# ---------------------------------------------------------
query_params = st.query_params
checkout_status = query_params.get("checkout")
plan = query_params.get("plan")

# ---------------------------------------------------------
# POST-CHECKOUT SUCCESS SCREEN (STOP HERE)
# ---------------------------------------------------------
if checkout_status == "success":
    st.success("🎉 Subscription activated!")

    if plan:
        st.markdown(f"### Current plan: **{plan.capitalize()}**")

    st.markdown(
        """
        Your subscription is now active.  
        You can immediately start generating summaries.
        """
    )

    st.page_link(
        "streamlit/pages/1_Upload_Data.py",
        label="➡️ Go to Upload Data",
        icon="📤",
    )

    st.stop()

# ---------------------------------------------------------
# NORMAL BILLING PAGE
# ---------------------------------------------------------
st.title("Billing & Subscription")

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.get("billing_email", ""),
)

if email:
    st.session_state["billing_email"] = email

st.divider()
st.subheader("Compare plans & upgrade")

PLANS = {
    "basic": {"label": "Basic", "price": "$9.99 / month"},
    "pro": {"label": "Pro", "price": "$19.99 / month"},
    "enterprise": {"label": "Enterprise", "price": "$39.99 / month"},
}

def start_checkout(plan_key: str):
    if not email:
        st.error("Please enter your billing email first.")
        return

    with st.spinner("Creating Stripe Checkout session..."):
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"email": email, "plan": plan_key},
            timeout=20,
        )

    if resp.status_code != 200:
        st.error("Failed to start checkout.")
        return

    checkout_url = resp.json().get("url")
    if not checkout_url:
        st.error("Checkout URL missing.")
        return

    # 🔥 REAL AUTO-REDIRECT (no button)
    components.html(
        f"""
        <script>
            window.location.href = "{checkout_url}";
        </script>
        """,
        height=0,
    )

cols = st.columns(3)

for col, key in zip(cols, PLANS.keys()):
    with col:
        st.markdown(f"### {PLANS[key]['label']}")
        st.markdown(PLANS[key]["price"])
        st.button(
            f"Choose {PLANS[key]['label']}",
            key=key,
            on_click=start_checkout,
            args=(key,),
        )
