# streamlit/pages/2_Billing.py
import os
import requests
import streamlit as st

def _get_backend_url() -> str:
    try:
        return st.secrets["backend_url"].rstrip("/")
    except Exception:
        return os.getenv("BACKEND_URL", "").rstrip("/")

BACKEND_URL = _get_backend_url()


def _clear_query_params():
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()

st.title("Billing & Plans")
st.caption("Choose a plan and manage your subscription.")

# --- Collect user email (simple identity) ---
st.subheader("Your email")
email = st.text_input(
    "We use this to link your subscription and summaries.",
    value=st.session_state.get("user_email", ""),
    placeholder="you@example.com",
)
if email:
    st.session_state["user_email"] = email.strip().lower()

# --- Handle redirect from Stripe ---
qp = getattr(st, "query_params", st.experimental_get_query_params)()
status = qp.get("status", [""])[0] if isinstance(qp, dict) else ""
session_id = qp.get("session_id", [""])[0] if isinstance(qp, dict) else ""

portal_url = None

if status == "success" and session_id:
    if not BACKEND_URL:
        st.error(
            "BACKEND_URL is not configured for this Streamlit service. "
            "Set it to your backend Render URL."
        )
    else:
        with st.spinner("Confirming your subscription…"):
            try:
                r = requests.get(
                    f"{BACKEND_URL}/checkout-success",
                    params={"session_id": session_id},
                    timeout=20,
                )
                if r.status_code == 200:
                    data = r.json() or {}
                    if data.get("has_active_subscription"):
                        st.success(
                            f"Subscription active for {data.get('email') or 'your account'} 🎉"
                        )
                    else:
                        st.warning(
                            "We could not confirm an active subscription for this session."
                        )
                    portal_url = data.get("portal_url")
                else:
                    st.error(
                        f"Could not confirm subscription ({r.status_code}): {r.text[:300]}"
                    )
            except requests.RequestException as e:
                st.error(f"Network error while confirming subscription: {e}")
    _clear_query_params()
elif status == "cancelled":
    st.info("Checkout cancelled. You have not been charged.", icon="ℹ️")
    _clear_query_params()

if portal_url:
    st.link_button(
        "Open Billing Portal",
        portal_url,
        type="secondary",
        help="Update payment method, view invoices, or cancel your subscription.",
    )

st.divider()

def start_checkout(plan: str, email: str):
    if not BACKEND_URL:
        st.error("BACKEND_URL is not configured.")
        return
    if not email.strip():
        st.error("Please enter your email before choosing a plan.")
        return

    try:
        r = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan, "email": email.strip().lower()},
            timeout=20,
        )
        if r.status_code == 200:
            url = (r.json() or {}).get("url")
            if not url:
                st.error("Backend did not return a checkout URL.")
                return
            st.success("Redirecting to Stripe Checkout…")
            st.markdown(
                f"""
                <meta http-equiv="refresh" content="0; url={url}">
                <p>If you are not redirected, <a href="{url}">click here</a>.</p>
                """,
                unsafe_allow_html=True,
            )
        else:
            try:
                payload = r.json()
                msg = payload.get("detail") or payload
            except Exception:
                msg = r.text
            st.error(f"Checkout failed ({r.status_code}): {msg}")
    except requests.RequestException as e:
        st.error(f"Network error starting checkout: {e}")

st.subheader("Choose your plan")

cols = st.columns(3)

with cols[0]:
    st.markdown("#### Basic")
    st.markdown("**$9.99 / month**")
    st.caption("Perfect for solo clinicians getting started.")
    st.markdown(
        """
        - Upload short visit notes  
        - Generate concise patient summaries  
        - Email-ready bullet points
        """
    )
    if st.button("Choose Basic", key="choose_basic"):
        start_checkout("basic", email)

with cols[1]:
    st.markdown("#### Pro")
    st.markdown("**$19.99 / month**")
    st.caption("For growing practices that want deeper summaries.")
    st.markdown(
        """
        - Longer notes and multi-page reports  
        - Richer summaries with more detail  
        - Priority processing
        """
    )
    if st.button("Choose Pro", key="choose_pro"):
        start_checkout("pro", email)

with cols[2]:
    st.markdown("#### Enterprise")
    st.markdown("**$49.99 / month**")
    st.caption("For organizations that need scale and customization.")
    st.markdown(
        """
        - High-volume usage  
        - Custom summary templates  
        - Dedicated support & onboarding
        """
    )
    if st.button("Choose Enterprise", key="choose_enterprise"):
        start_checkout("enterprise", email)

st.divider()
st.caption(f"Using backend: `{BACKEND_URL or 'BACKEND_URL not configured'}`")
