import os
import requests
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

# ---------- Config ----------

# Try Streamlit secrets first, then environment, then last-resort default
BACKEND_URL = (
    st.secrets.get("BACKEND_URL", None)
    if hasattr(st, "secrets")
    else None
)
if not BACKEND_URL:
    BACKEND_URL = os.environ.get(
        "BACKEND_URL",
        "https://ai-report-backend-ubrx.onrender.com",
    )

PLAN_LIMITS = {
    "free": {
        "label": "Free",
        "max_documents": 5,
        "max_chars": 200_000,
    },
    "basic": {
        "label": "Basic",
        "max_documents": 20,
        "max_chars": 400_000,
    },
    "pro": {
        "label": "Pro",
        "max_documents": 75,
        "max_chars": 1_500_000,
    },
    "enterprise": {
        "label": "Enterprise",
        "max_documents": 250,
        "max_chars": 5_000_000,
    },
}


# ---------- Helper functions ----------

def get_subscription_status(email: str):
    """Call backend /subscription-status endpoint."""
    if not email:
        return None

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=10,
        )
        if resp.status_code == 404:
            # endpoint not found – just act like "no subscription"
            return {"status": "none", "plan": None, "current_period_end": None}

        resp.raise_for_status()
        data = resp.json()
        return data
    except Exception as exc:
        st.error(f"Error checking subscription status: {exc}")
        return None


def start_checkout(plan: str, billing_email: str, coupon_code: str | None):
    """Create a Stripe Checkout session via backend and redirect the user."""
    if not billing_email:
        st.error("Please enter your billing email first.")
        return

    if plan not in ("basic", "pro", "enterprise"):
        st.error("Invalid plan selected.")
        return

    if not BACKEND_URL:
        st.error(
            "BACKEND_URL is not configured for the Streamlit app. "
            "Please set it in Render or in .streamlit/secrets.toml."
        )
        return

    payload = {
        "email": billing_email,
        "plan": plan,
    }
    if coupon_code:
        payload["coupon"] = coupon_code.strip()

    try:
        with st.spinner("Starting secure Stripe checkout..."):
            resp = requests.post(
                f"{BACKEND_URL}/create-checkout-session",
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        st.error(f"Network error starting checkout: {exc}")
        return

    checkout_url = (
        data.get("session_url")
        or data.get("url")
        or data.get("checkout_url")
    )

    if not checkout_url:
        st.error("The billing server did not return a checkout URL.")
        st.write("Raw server response:")
        st.json(data)
        return

    # Show a message + fallback link
    st.success("Redirecting you to secure Stripe Checkout…")
    st.markdown(
        f"[Click here if you are not redirected automatically]({checkout_url})"
    )

    # Hard redirect using a tiny HTML snippet
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


# ---------- Page UI ----------

st.title("Billing & Subscription")
st.caption(
    "Pick the plan that best fits your workload. "
    "You can upgrade later as your needs grow."
)

if not BACKEND_URL:
    st.error(
        "BACKEND_URL environment variable is not set for this app. "
        "Set it in the Render dashboard before using billing."
    )
    st.stop()

# ----- Step 1 – Enter / save email -----

st.markdown("### Step 1 – Enter your email")

default_email = st.session_state.get("billing_email", "")
billing_email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=default_email,
    key="billing_email_input",
)

coupon_code = st.text_input(
    "Coupon code (optional)",
    value=st.session_state.get("coupon_code", ""),
    key="coupon_code_input",
)

col_save, _ = st.columns([1, 4])

subscription_info = None
with col_save:
    if st.button("Save email & check current plan"):
        if not billing_email:
            st.error("Please enter an email address.")
        else:
            st.session_state["billing_email"] = billing_email
            st.session_state["coupon_code"] = coupon_code
            subscription_info = get_subscription_status(billing_email)

# If we didn’t just click the button, try to load saved status once
if subscription_info is None and st.session_state.get("billing_email"):
    subscription_info = get_subscription_status(
        st.session_state["billing_email"]
    )

# ----- Show current plan -----

if subscription_info is None:
    st.info("Enter your billing email and click the button to see your plan.")
else:
    status = subscription_info.get("status")
    plan_key = subscription_info.get("plan") or "free"
    current_plan_label = PLAN_LIMITS.get(plan_key, {}).get(
        "label", plan_key.title()
    )
    plan_info = PLAN_LIMITS.get(plan_key, PLAN_LIMITS["free"])

    if status == "none" or not subscription_info.get("plan"):
        st.info("No active subscription found for this email.")
    else:
        end_ts = subscription_info.get("current_period_end")
        period_text = ""
        if end_ts:
            try:
                dt = datetime.fromtimestamp(end_ts)
                period_text = f"Your current period renews around **{dt:%b %d, %Y}**."
            except Exception:
                pass

        st.markdown("### Current plan")
        st.info(
            f"**Status:** {current_plan_label} plan  \n"
            f"You can upload up to **{plan_info['max_documents']} reports per month** "
            f"and a total of about **{plan_info['max_chars']:,} characters**.  \n"
            f"{period_text}"
        )

# ---------- Step 2 – Compare & upgrade ----------

st.markdown("### Step 2 – Compare plans & upgrade")
st.write(
    "Pick the plan that best fits your workload. "
    "You can upgrade later as your needs grow."
)

col_basic, col_pro, col_enterprise = st.columns(3)

# BASIC
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
        start_checkout(
            "basic",
            st.session_state.get("billing_email", billing_email),
            st.session_state.get("coupon_code", coupon_code),
        )

# PRO
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
        start_checkout(
            "pro",
            st.session_state.get("billing_email", billing_email),
            st.session_state.get("coupon_code", coupon_code),
        )

# ENTERPRISE
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
        start_checkout(
            "enterprise",
            st.session_state.get("billing_email", billing_email),
            st.session_state.get("coupon_code", coupon_code),
        )

st.caption(
    "After you subscribe, return to the **Upload Data** tab to start generating "
    "client-ready summaries from your reports."
)
