import os
import requests
import streamlit as st

# --- read backend URL without triggering secrets banner ---
def _get_backend_url() -> str:
    # 1) env var on Render (recommended)
    url = os.getenv("BACKEND_URL", "").rstrip("/")
    if url:
        return url
    # 2) optional Streamlit secrets (only used if you create a secrets.toml)
    try:
        return st.secrets.get("backend_url", "").rstrip("/")
    except Exception:
        return ""

BACKEND_URL = _get_backend_url()

# show post-checkout status, if any
status = st.query_params.get("status", [""])[0]
if status == "success":
    st.success("Payment successful—thanks! Your plan is active.")
elif status == "cancelled":
    st.info("Checkout cancelled.")

st.header("Plans")

def start_checkout(plan: str):
    if not BACKEND_URL:
        st.error("BACKEND_URL not configured.")
        return
    try:
        r = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan},  # server resolves plan -> price
            timeout=20,
        )
    except requests.RequestException as e:
        st.error(f"Network error: {e}")
        return

    if r.status_code == 200:
        url = (r.json() or {}).get("url")
        if not url:
            st.error("Backend did not return a checkout URL.")
            return
        # redirect
        st.markdown(
            f'<meta http-equiv="refresh" content="0; url={url}">',
            unsafe_allow_html=True,
        )
        st.write(f"[Open Stripe Checkout]({url})")
    else:
        try:
            msg = r.json().get("detail")
        except Exception:
            msg = r.text
        st.error(f"Checkout failed ({r.status_code}): {msg}")

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

# tiny debug footer (safe to keep or remove)
if BACKEND_URL:
    st.caption(f"Using backend: {BACKEND_URL}")
