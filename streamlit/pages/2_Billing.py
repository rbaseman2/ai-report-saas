# streamlit/pages/2_Billing.py
import os, requests, streamlit as st

# In streamlit/pages/2_Billing.py, near top of the page:
status = st.query_params.get("status", [""])[0]
if status == "success":
    st.success("Payment successful—thanks! Your plan is active.")
elif status == "cancelled":
    st.info("Checkout cancelled.")



def _get_backend_url() -> str:
    # Try secrets only if present; otherwise fall back to env var
    try:
        # This will throw if secrets.toml doesn't exist
        return st.secrets["backend_url"].rstrip("/")
    except Exception:
        return os.getenv("BACKEND_URL", "").rstrip("/")

BACKEND_URL = _get_backend_url()
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
            # Auto-redirect (opens in same tab)
            st.markdown(f"""
                <meta http-equiv="refresh" content="0; url={url}">
                <p>If you are not redirected, <a href="{url}">click here</a>.</p>
            """, unsafe_allow_html=True)
        else:
            try:
                payload = r.json()
                msg = payload.get("detail") or payload
            except Exception:
                msg = r.text
            st.error(f"Checkout failed ({r.status_code}): {msg}")
    except requests.RequestException as e:
        st.error(f"Network error starting checkout: {e}")

st.header("Plans")
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
