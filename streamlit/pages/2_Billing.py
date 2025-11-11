# streamlit/pages/2_Billing.py
import os
import requests
import streamlit as st

# ---- Resolve backend URL from secrets or env --------------------------------
def _get_backend_url() -> str:
    try:
        return st.secrets["backend_url"].rstrip("/")
    except Exception:
        return os.getenv("BACKEND_URL", "").rstrip("/")

BACKEND_URL = _get_backend_url()

st.header("Plans")

# ---- Handle Stripe return (status + session details) ------------------------
status = st.query_params.get("status", [""])[0]
session_id = st.query_params.get("session_id", [""])[0]

customer_id = None
subscription_id = None

if status == "success":
    st.success("Payment successful — your plan is active.")
    if BACKEND_URL and session_id:
        try:
            r = requests.get(f"{BACKEND_URL}/checkout-session", params={"session_id": session_id}, timeout=15)
            if r.ok:
                data = r.json()
                customer_id     = data.get("customer_id")
                subscription_id = data.get("subscription_id")
                plan_id         = data.get("plan_id")
                st.caption(f"Customer: {customer_id} · Subscription: {subscription_id} · Plan: {plan_id}")
            else:
                st.warning(f"Could not fetch session details: {r.text}")
        except Exception as e:
            st.warning(f"Could not fetch session details: {e}")
elif status == "cancelled":
    st.info("Checkout cancelled.")

# ---- Start Checkout ---------------------------------------------------------
def start_checkout(plan: str):
    if not BACKEND_URL:
        st.error("BACKEND_URL is not set in Streamlit (env var or st.secrets['backend_url']).")
        return
    try:
        r = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan},  # ONLY the plan slug
            timeout=20,
        )
        if r.status_code == 200:
            url = (r.json() or {}).get("url")
            if not url:
                st.error("Backend did not return a checkout URL.")
                return
            st.success("Redirecting to Stripe Checkout…")
            # auto-redirect (same tab)
            st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)
            st.markdown(f'If you are not redirected, <a href="{url}">click here</a>.', unsafe_allow_html=True)
        else:
            try:
                msg = r.json().get("detail")
            except Exception:
                msg = r.text
            st.error(f"Checkout failed ({r.status_code}): {msg}")
    except requests.RequestException as e:
        st.error(f"Network error starting checkout: {e}")

# ---- Plan buttons -----------------------------------------------------------
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Choose Basic"):
        start_checkout("basic")
with col2:
    if st.button("Choose Pro"):
        start_checkout("pro")
with col3:
    if st.button("Choose Enterprise"):
        start_checkout("enterprise")

st.divider()

# ---- Customer Portal (appears after success) --------------------------------
if customer_id:
    if st.button("Open customer portal"):
        try:
            r = requests.post(f"{BACKEND_URL}/create-portal-session",
                              json={"customer_id": customer_id},
                              timeout=15)
            if r.ok and r.json().get("url"):
                url = r.json()["url"]
                st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)
                st.markdown(f'If you are not redirected, <a href="{url}">open the portal</a>.', unsafe_allow_html=True)
            else:
                st.error(f"Could not create portal session: {r.text}")
        except Exception as e:
            st.error(f"Could not create portal session: {e}")
else:
    st.caption("After a successful checkout, you’ll see a Manage Subscription button here.")
