# pages/Billing.py

import os
import time
import requests
from requests.adapters import HTTPAdapter, Retry
import streamlit as st

# ---------- Page setup ----------
st.set_page_config(page_title="Billing", page_icon="💳")
st.title("Billing")
st.caption("Choose a plan, manage subscription, etc.")

# Pretend-auth for demo; replace with your real user identity
if "user_email" not in st.session_state:
    st.session_state["user_email"] = "test@example.com"
email = st.session_state["user_email"]

# ---------- Environment ----------
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")
PRICE_BASIC = os.environ.get("PRICE_BASIC", "price_...basic")
PRICE_PRO = os.environ.get("PRICE_PRO", "price_...pro")
PRICE_ENTERPRISE = os.environ.get("PRICE_ENTERPRISE", "price_...enterprise")

# ---------- Helpers ----------
def redirect_now(url: str):
    st.markdown(
        f'<script>window.location.href="{url}";</script>',
        unsafe_allow_html=True,
    )
    # visible fallback (helps if JS is disabled)
    st.link_button("Continue", url)
    st.stop()

def wait_for_backend(base_url: str, seconds: int = 60) -> bool:
    """Poll GET /health while Render wakes the free instance."""
    health = f"{base_url.rstrip('/')}/health"
    start = time.time()
    with st.spinner("Waking backend… (Render free instances sleep)"):
        while time.time() - start < seconds:
            try:
                r = requests.get(health, timeout=5)
                if r.ok:
                    return True
            except Exception:
                pass
            time.sleep(2)
    return False

def post_with_retry(url: str, payload: dict, timeout: int = 60):
    """Resilient POST with retries for 502/503/504 from cold starts."""
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1.2,                 # 1.2s, 2.4s, 3.6s…
        status_forcelist=[502, 503, 504],
        allowed_methods=["POST", "GET"],
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s.post(url, json=payload, timeout=timeout)

def start_checkout(price_id: str):
    """Create Stripe Checkout session and redirect."""
    resp = post_with_retry(
        f"{BACKEND_URL}/create-checkout-session",
        {"price_id": price_id, "email": email},
        timeout=60,
    )
    if not resp.ok:
        st.error(f"Checkout error: HTTP {resp.status_code} — {resp.text}")
        return
    data = resp.json()
    url = data.get("url")
    if not url:
        st.error("Checkout error: backend did not return a URL.")
        return
    redirect_now(url)

def open_customer_portal():
    resp = post_with_retry(
        f"{BACKEND_URL}/create-portal-session",
        {"email": email},
        timeout=60,
    )
    if not resp.ok:
        st.error(f"Portal error: HTTP {resp.status_code} — {resp.text}")
        return
    data = resp.json()
    url = data.get("url")
    if not url:
        st.error("Portal error: backend did not return a URL.")
        return
    redirect_now(url)

# ---------- Wake backend first ----------
if not wait_for_backend(BACKEND_URL, seconds=60):
    st.error("Backend is still waking up. Please try again in a moment.")
    st.stop()

# ---------- Debug (optional) ----------
with st.expander("Debug (you can hide this later)", expanded=False):
    st.write(
        {
            "email": email,
            "BACKEND_URL": BACKEND_URL,
            "PRICE_BASIC": PRICE_BASIC,
            "PRICE_PRO": PRICE_PRO,
            "PRICE_ENTERPRISE": PRICE_ENTERPRISE,
        }
    )

st.divider()
st.subheader("Plans")

# ---------- UI ----------
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Basic\n$9.99/mo • Includes: core features")
    if st.button("Choose Basic", type="primary"):
        start_checkout(PRICE_BASIC)

with col2:
    st.markdown("### Pro\n$29.99/mo • Includes: premium reports, bulk exports")
    if st.button("Choose Pro"):
        start_checkout(PRICE_PRO)

with col3:
    st.markdown("### Enterprise\n$99.99/mo • Priority support & SSO")
    if st.button("Choose Enterprise"):
        start_checkout(PRICE_ENTERPRISE)

st.divider()
st.subheader("Manage subscription")
if st.button("Open customer portal"):
    open_customer_portal()
