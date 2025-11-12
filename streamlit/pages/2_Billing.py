# streamlit/pages/2_Billing.py
import os
import requests
import streamlit as st

def _get_backend_url() -> str:
    url = os.getenv("BACKEND_URL", "").rstrip("/")
    if url:
        return url
    try:
        return st.secrets.get("backend_url", "").rstrip("/")
    except Exception:
        return ""

BACKEND_URL = _get_backend_url()

# ---- Robust query param parsing --------------------------------------------
qp = st.query_params
status_raw = qp.get("status", [""])[0]  # may contain junk if URL had '?status=success?session_id=...'
session_id = qp.get("session_id", [""])[0]

# tolerate accidental second '?'
# e.g. 'success?session_id=cs_123' -> 'success'
status = status_raw.split("?")[0].split("&")[0].lower()

# ---------------------------------------------------------------------------
st.header("Plans")

def start_checkout(plan: str):
    if not BACKEND_URL:
        st.error("BACKEND_URL not configured.")
        return
    try:
        r = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan},
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
        st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)
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

# --- Post-checkout UX -------------------------------------------------------
if status == "success" or session_id:
    st.success("Payment successful—thanks! Your plan is active.")
    st.caption("You can manage your subscription below.")

    if st.button("Manage subscription"):
        try:
            r = requests.post(
                f"{BACKEND_URL}/create-portal-session",
                json={"session_id": session_id},
                timeout=20,
            )
        except requests.RequestException as e:
            st.error(f"Network error: {e}")
        else:
            if r.status_code == 200:
                portal_url = (r.json() or {}).get("url")
                if portal_url:
                    st.markdown(
                        f'<meta http-equiv="refresh" content="0; url={portal_url}">',
                        unsafe_allow_html=True,
                    )
                    st.write(f"[Open Subscription Portal]({portal_url})")
                else:
                    st.error("Portal URL not returned by backend.")
            else:
                try:
                    msg = r.json().get("detail")
                except Exception:
                    msg = r.text
                st.error(f"Could not open portal ({r.status_code}): {msg}")

# small debug footer
if BACKEND_URL:
    st.caption(f"Using backend: {BACKEND_URL}")
