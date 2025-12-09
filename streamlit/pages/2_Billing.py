# streamlit/pages/2_Billing.py

import os
import requests
import streamlit as st

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------
# Read backend URL from Render env var
BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",  # safe default
).rstrip("/")

CREATE_CHECKOUT_URL = f"{BACKEND_URL}/create-checkout-session"
SUB_STATUS_URL = f"{BACKEND_URL}/subscription-status"


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def get_subscription_status(email: str):
    try:
        resp = requests.get(SUB_STATUS_URL, params={"email": email}, timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Error checking subscription: {e}")
        return None


def start_checkout(plan: str, email: str, coupon: str | None = None):
    payload = {"plan": plan, "email": email}
    if coupon:
        payload["coupon"] = coupon.strip()

    try:
        resp = requests.post(CREATE_CHECKOUT_URL, json=payload, timeout=20)
        resp.raise_for_status()
    except requests.HTTPError as e:
        try:
            data = resp.json()
            msg = data.get("detail") or data.get("error") or str(e)
        except Exception:
            msg = str(e)
        st.error(f"Checkout error: {msg}")
        return None
    except Exception as e:
        st.error(f"Network error starting checkout: {e}")
        return None

    data = resp.json()
    return data.get("checkout_url")


# --------------------------------------------------------------------
# UI
# --------------------------------------------------------------------
st.set_page_config(page_title="Billing & Subscription", page_icon="💳")

st.title("Billing & Subscription")

st.markdown("### Step 1 – Enter your email")

# Keep email in session so it persists between reruns
if "billing_email" not in st.session_state:
    st.session_state.billing_email = ""

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.billing_email,
    key="billing_email_input",
)

coupon_code = st.text_input(
    "Coupon code (optional)",
    value=st.session_state.get("coupon_code", ""),
    placeholder="welcome",
    key="coupon_code_input",
)

col_btn, _ = st.columns([1, 3])
with col_btn:
    if st.button("Save email & check current plan", use_container_width=True):
        if not email:
            st.warning("Please enter an email first.")
        else:
            st.session_state.billing_email = email
            st.session_state.coupon_code = coupon_code
            status = get_subscription_status(email)
            if status is None:
                st.info("No active subscription found for this email.")
            else:
                plan = status.get("plan") or status.get("price_id", "unknown")
                st.success(f"Active subscription: **{plan}**")
                if status.get("current_period_end"):
                    st.write(
                        f"Renews on: **{status['current_period_end']}** "
                        "(UTC timestamp from Stripe)."
                    )
                if status.get("status"):
                    st.write(f"Status: **{status['status']}**")

st.markdown("---")
st.markdown("### Step 2 – Compare plans & upgrade")

if not email:
    st.info("Enter your email above before choosing a plan.")

cols = st.columns(3)

# ---------------------- Basic ----------------------
with cols[0]:
    st.subheader("Basic")
    st.caption("$9.99 / month")
    st.markdown(
        """
- Up to 20 reports / month  
- Up to 400k characters / month  
- Executive summaries + key insights  
        """
    )
    if st.button("Choose Basic", key="choose_basic", use_container_width=True):
        if not email:
            st.warning("Please enter and save your email first.")
        else:
            checkout_url = start_checkout(
                plan="basic",
                email=email,
                coupon=coupon_code or st.session_state.get("coupon_code", ""),
            )
            if checkout_url:
                st.markdown(
                    f'<meta http-equiv="refresh" content="0; url={checkout_url}" />',
                    unsafe_allow_html=True,
                )
                st.info("Redirecting to Stripe checkout… If nothing happens, "
                        f"[click here]({checkout_url}).")

# ---------------------- Pro ----------------------
with cols[1]:
    st.subheader("Pro")
    st.caption("$19.99 / month")
    st.markdown(
        """
- Up to 75 reports / month  
- Up to 1.5M characters / month  
- Action items, risks, and opportunity insights  
        """
    )
    if st.button("Choose Pro", key="choose_pro", use_container_width=True):
        if not email:
            st.warning("Please enter and save your email first.")
        else:
            checkout_url = start_checkout(
                plan="pro",
                email=email,
                coupon=coupon_code or st.session_state.get("coupon_code", ""),
            )
            if checkout_url:
                st.markdown(
                    f'<meta http-equiv="refresh" content="0; url={checkout_url}" />',
                    unsafe_allow_html=True,
                )
                st.info("Redirecting to Stripe checkout… If nothing happens, "
                        f"[click here]({checkout_url}).")

# ---------------------- Enterprise ----------------------
with cols[2]:
    st.subheader("Enterprise")
    st.caption("$39.99 / month")
    st.markdown(
        """
- Up to 250 reports / month  
- Up to 5M characters / month  
- Team accounts, shared templates, & premium support  
        """
    )
    if st.button("Choose Enterprise", key="choose_enterprise", use_container_width=True):
        if not email:
            st.warning("Please enter and save your email first.")
        else:
            checkout_url = start_checkout(
                plan="enterprise",
                email=email,
                coupon=coupon_code or st.session_state.get("coupon_code", ""),
            )
            if checkout_url:
                st.markdown(
                    f'<meta http-equiv="refresh" content="0; url={checkout_url}" />',
                    unsafe_allow_html=True,
                )
                st.info("Redirecting to Stripe checkout… If nothing happens, "
                        f"[click here]({checkout_url}).")

st.markdown(
    """
After you subscribe, return to the **Upload Data** tab to start generating
client-ready summaries from your reports.
"""
)
