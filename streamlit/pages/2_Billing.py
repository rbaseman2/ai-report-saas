# streamlit/pages/2_Billing.py

import os
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Billing & Subscription", page_icon="💳")

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",  # fallback
)

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
def get_subscription_status(email: str):
    """Call backend /subscription-status and return dict or None on no sub."""
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=10,
        )
    except Exception as e:
        st.error(f"Could not reach billing backend: {e}")
        return None

    # 404 = no subscription
    if resp.status_code == 404:
        return {"status": "none"}

    if not resp.ok:
        st.error(
            f"Error checking subscription status ({resp.status_code}): "
            f"{resp.text}"
        )
        return None

    try:
        data = resp.json()
    except Exception:
        st.error("Unexpected response from billing backend.")
        return None

    # Normalize keys so UI doesn’t show 'unknown'
    return {
        "status": data.get("status", "unknown"),
        "plan": data.get("plan"),  # may be None
        "current_period_end": data.get("current_period_end"),
    }


def start_checkout(plan: str, email: str):
    """Call backend /create-checkout-session and redirect to Stripe."""
    payload = {"plan": plan, "email": email}

    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json=payload,
            timeout=20,
        )
    except Exception as e:
        st.error(f"Could not start checkout: {e}")
        return

    if not resp.ok:
        st.error(
            f"Checkout error ({resp.status_code}): {resp.text}"
        )
        return

    try:
        data = resp.json()
        checkout_url = data["url"]
    except Exception:
        st.error("Unexpected response from billing backend.")
        return

    # Auto-redirect to Stripe Checkout
    components.html(
        f"""
        <html>
          <head>
            <meta http-equiv="refresh" content="0; url={checkout_url}" />
          </head>
          <body></body>
        </html>
        """,
        height=0,
    )


# -------------------------------------------------------------------
# Page layout
# -------------------------------------------------------------------
st.title("Billing & Subscription")

st.markdown("### Step 1 – Enter your email")

# Use session_state so the email sticks around
if "billing_email" not in st.session_state:
    st.session_state.billing_email = ""

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.billing_email,
    key="billing_email_input",
)

col1, _ = st.columns([1, 3])
with col1:
    check_btn = st.button("Save email & check current plan")

subscription_info = None
if check_btn:
    if not email.strip():
        st.error("Please enter an email address first.")
    else:
        subscription_info = get_subscription_status(email.strip())

# If user just came back from Stripe (success URL), also check status
if subscription_info is None and email.strip():
    # Lightweight best-effort: don’t show errors if this fails silently
    try:
        subscription_info = get_subscription_status(email.strip())
    except Exception:
        subscription_info = None

# -------------------------------------------------------------------
# Subscription status display (no “unknown” wording)
# -------------------------------------------------------------------
if subscription_info:
    status = subscription_info.get("status", "none")
    plan = subscription_info.get("plan")

    if status == "active":
        plan_text = f" – {plan}" if plan else ""
        st.success(f"Active subscription{plan_text}")
        st.write("Status: **active**")
    elif status in ("incomplete", "past_due", "trialing"):
        st.warning(f"Subscription status: **{status}**")
        if plan:
            st.write(f"Plan: **{plan}**")
    else:
        st.info("No active subscription found for this email.")
        st.write("Status: **none**")
else:
    st.info("Enter your email and click **Save email & check current plan** to see your status.")

st.markdown("---")
st.markdown("### Step 2 – Compare plans & upgrade")
st.write("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

# -------------------------------------------------------------------
# Plans
# -------------------------------------------------------------------
col_basic, col_pro, col_enterprise = st.columns(3)

with col_basic:
    st.subheader("Basic")
    st.write("$9.99 / month")
    st.markdown(
        """
        - Up to 20 reports / month  
        - Up to 400k characters / month  
        - Executive summaries + key insights  
        """
    )
    if st.button("Choose Basic", key="choose_basic"):
        if not email.strip():
            st.error("Please enter your billing email above before choosing a plan.")
        else:
            start_checkout("basic", email.strip())

with col_pro:
    st.subheader("Pro")
    st.write("$19.99 / month")
    st.markdown(
        """
        - Up to 75 reports / month  
        - Up to 1.5M characters / month  
        - Action items, risks, and opportunity insights  
        """
    )
    if st.button("Choose Pro", key="choose_pro"):
        if not email.strip():
            st.error("Please enter your billing email above before choosing a plan.")
        else:
            start_checkout("pro", email.strip())

with col_enterprise:
    st.subheader("Enterprise")
    st.write("$39.99 / month")
    st.markdown(
        """
        - Up to 250 reports / month  
        - Up to 5M characters / month  
        - Team accounts, shared templates, & premium support  
        """
    )
    if st.button("Choose Enterprise", key="choose_enterprise"):
        if not email.strip():
            st.error("Please enter your billing email above before choosing a plan.")
        else:
            start_checkout("enterprise", email.strip())

st.markdown(
    """
After you subscribe, return to the **Upload Data** tab to start generating
client-ready summaries from your reports.
"""
)
