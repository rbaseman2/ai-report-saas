# streamlit/pages/2_Billing.py

import os
import requests
import streamlit as st

st.set_page_config(page_title="Billing & Subscription", page_icon="💳")

# Get backend URL from environment variable
BACKEND_URL = os.getenv("BACKEND_URL")

# --- Sidebar navigation (only existing pages) ---
st.sidebar.title("Navigation")
st.sidebar.page_link("Home.py", label="Home")
st.sidebar.page_link("pages/1_Upload_Data.py", label="Upload Data")
st.sidebar.page_link("pages/2_Billing.py", label="Billing", disabled=True)

st.title("Billing & Subscription")

if not BACKEND_URL:
    st.error(
        "BACKEND_URL environment variable is not set for the frontend service.\n\n"
        "Go to the **Render dashboard → your Streamlit (frontend) service → Environment** "
        "and add `BACKEND_URL` pointing to your backend "
        "(e.g. `https://ai-report-backend-xxxx.onrender.com`)."
    )
    st.stop()

# Show success banner if returned from checkout
query_params = st.query_params
if query_params.get("status") == "success":
    st.success("Payment successful! Your subscription is now active.")

# -------------------------------------------------------
# Step 1 – Enter email
# -------------------------------------------------------
st.subheader("Step 1 – Enter your email")

billing_email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.get("billing_email", ""),
)

if st.button("Save email & check current plan"):
    if not billing_email:
        st.warning("Please enter an email.")
    else:
        st.session_state["billing_email"] = billing_email
        try:
            resp = requests.get(
                f"{BACKEND_URL.rstrip('/')}/subscription-status",
                params={"email": billing_email},
                timeout=20,
            )
            if resp.status_code != 200:
                st.error(f"Unexpected response from billing backend: {resp.text}")
            else:
                data = resp.json()
                status = data.get("status", "none")
                plan = data.get("plan")
                if status in ("active", "trialing"):
                    st.success(
                        f"Active subscription found: {plan.capitalize()} (status: {status})"
                    )
                else:
                    st.info("No active subscription found for this email.")

                st.session_state["current_plan"] = plan or None
        except Exception as e:
            st.error(f"Error contacting backend: {e}")

current_plan = st.session_state.get("current_plan")

st.markdown(f"**Status:** `{current_plan or 'none'}`")

# -------------------------------------------------------
# Step 2 – Compare plans & upgrade
# -------------------------------------------------------
st.markdown("---")
st.subheader("Step 2 – Compare plans & upgrade")
st.write("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Basic")
    st.markdown("**$9.99 / month**")
    st.markdown(
        """
- Up to 20 reports / month  
- Up to 400k characters / month  
- Executive summaries + key insights  
"""
    )
    basic_btn = st.button("Choose Basic", key="choose_basic")

with col2:
    st.markdown("### Pro")
    st.markdown("**$19.99 / month**")
    st.markdown(
        """
- Up to 75 reports / month  
- Up to 1.5M characters / month  
- Action items, risks, and opportunity insights  
"""
    )
    pro_btn = st.button("Choose Pro", key="choose_pro")

with col3:
    st.markdown("### Enterprise")
    st.markdown("**$39.99 / month**")
    st.markdown(
        """
- Up to 250 reports / month  
- Up to 5M characters / month  
- Team accounts, shared templates, & premium support  
"""
    )
    enterprise_btn = st.button("Choose Enterprise", key="choose_enterprise")

st.markdown("---")
st.subheader("Optional coupon")

coupon_code = st.text_input(
    "Coupon code (optional)",
    placeholder="welcome",
    value=st.session_state.get("coupon_code", ""),
)

if coupon_code:
    st.session_state["coupon_code"] = coupon_code

error_placeholder = st.empty()

def start_checkout(plan: str):
    if not billing_email:
        error_placeholder.warning("Please enter your billing email first.")
        return

    payload = {
        "email": billing_email,
        "plan": plan,
        "coupon_code": coupon_code or None,
    }

    try:
        resp = requests.post(
            f"{BACKEND_URL.rstrip('/')}/create-checkout-session",
            json=payload,
            timeout=40,
        )
        if resp.status_code != 200:
            error_placeholder.error(
                f"Checkout error: {resp.status_code} - {resp.text}"
            )
        else:
            data = resp.json()
            checkout_url = data["checkout_url"]
            st.markdown(
                f"[Click here to complete checkout]({checkout_url})",
                unsafe_allow_html=True,
            )
            st.info("If you are not redirected automatically, click the link above.")
    except Exception as e:
        error_placeholder.error(f"Error contacting billing backend: {e}")

if basic_btn:
    start_checkout("basic")
if pro_btn:
    start_checkout("pro")
if enterprise_btn:
    start_checkout("enterprise")

st.markdown(
    """
After you subscribe, return to the **Upload Data** tab to start generating client-ready
summaries from your reports.
"""
)
