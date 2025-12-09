import os
from typing import Optional

import requests
import streamlit as st

st.set_page_config(page_title="Billing & Subscription – AI Reports")

# ---------- Config ----------

DEFAULT_BACKEND_URL = "https://ai-report-backend-ubrx.onrender.com"
BACKEND_URL = st.secrets.get("BACKEND_URL", os.environ.get("BACKEND_URL", DEFAULT_BACKEND_URL))


def get_backend_url() -> str:
    if not BACKEND_URL:
        st.error(
            "Backend URL is not configured. "
            "Set BACKEND_URL in your Streamlit secrets or environment variables."
        )
        st.stop()
    return BACKEND_URL.rstrip("/")


# ---------- Helpers ----------


def fetch_subscription_status(email: str) -> Optional[dict]:
    try:
        resp = requests.get(
            f"{get_backend_url()}/subscription-status",
            params={"email": email},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # broad but safe for UI
        st.error(f"Error checking subscription status: {exc}")
        return None


def start_checkout(plan: str, email: str):
    try:
        resp = requests.post(
            f"{get_backend_url()}/create-checkout-session",
            json={"plan": plan, "email": email},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as exc:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = None
        message = detail or str(exc)
        st.error(f"Checkout error: {message}")
        return
    except Exception as exc:
        st.error(f"Unexpected error starting checkout: {exc}")
        return

    checkout_url = data.get("checkout_url")
    if not checkout_url:
        st.error("Backend did not return a checkout URL.")
        return

    st.success("Checkout session created. Opening Stripe Checkout…")
    # Auto-redirect
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={checkout_url}">', unsafe_allow_html=True
    )
    st.markdown(f"[If you are not redirected, click here to open Stripe Checkout.]({checkout_url})")


# ---------- UI ----------

st.title("Billing & Subscription")

st.markdown(
    """
Use this page to manage your AI Report subscription.
All billing is handled securely via Stripe.
"""
)

st.markdown("### Step 1 – Enter your email")

billing_email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.get("billing_email", ""),
)

if billing_email:
    st.session_state["billing_email"] = billing_email

st.info("You will be able to enter a **promotion/coupon code directly on the Stripe Checkout page.**")

status_box = st.empty()

if billing_email:
    status = fetch_subscription_status(billing_email)
    if status is None:
        status_box.warning("Unable to retrieve subscription status.")
    elif not status["active"]:
        status_box.info("No active subscription found for this email.")
    else:
        plan_label = status.get("plan") or "Unknown plan"
        status_box.success(
            f"Active subscription detected for **{billing_email}** "
            f"on the **{plan_label.capitalize()}** plan (status: {status['status']})."
        )
else:
    status_box.info("Enter your billing email above to check your current subscription.")

st.markdown("---")
st.markdown("### Step 2 – Compare plans & upgrade")

col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("Basic")
    st.markdown("**$9.99 / month**")
    st.markdown(
        """
- Up to 20 reports / month  
- Up to 400k characters / month  
- Executive summaries + key insights  
"""
    )
    if st.button("Choose Basic", key="choose_basic"):
        if not billing_email:
            st.error("Please enter your billing email first.")
        else:
            start_checkout("basic", billing_email)

with col2:
    st.subheader("Pro")
    st.markdown("**$19.99 / month**")
    st.markdown(
        """
- Up to 75 reports / month  
- Up to 1.5M characters / month  
- Action items, risks, and opportunity insights  
"""
    )
    if st.button("Choose Pro", key="choose_pro"):
        if not billing_email:
            st.error("Please enter your billing email first.")
        else:
            start_checkout("pro", billing_email)

with col3:
    st.subheader("Enterprise")
    st.markdown("**$39.99 / month**")
    st.markdown(
        """
- Up to 250 reports / month  
- Up to 5M characters / month  
- Team accounts, shared templates, & premium support  
"""
    )
    if st.button("Choose Enterprise", key="choose_enterprise"):
        if not billing_email:
            st.error("Please enter your billing email first.")
        else:
            start_checkout("enterprise", billing_email)

st.markdown("---")

st.caption(
    "You can upgrade later as your needs grow. All subscriptions are managed securely via Stripe. "
    "To cancel or change plans, use the link in your Stripe receipt emails or contact support."
)
