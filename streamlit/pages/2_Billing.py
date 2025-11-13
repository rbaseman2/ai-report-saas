# streamlit/pages/2_Billing.py

import os
import requests
import streamlit as st

# ---------------------------------------------------------------------
# Backend URL helper
# ---------------------------------------------------------------------


def _get_backend_url() -> str:
    """
    Prefer BACKEND_URL env var (Render style), and only fall back to
    st.secrets["backend_url"] when running locally and there is no env var.
    This avoids the 'No secrets found' warning on Render.
    """
    env_val = os.getenv("BACKEND_URL", "").rstrip("/")
    if env_val:
        return env_val

    # Optional: local dev using .streamlit/secrets.toml
    try:
        return st.secrets["backend_url"].rstrip("/")
    except Exception:
        return ""

BACKEND_URL = _get_backend_url()


def _debug_backend_url():
    st.caption(
        f"Using backend: {BACKEND_URL or 'NOT CONFIGURED'}",
        help="This is the FastAPI/Stripe backend URL.",
    )


# ---------------------------------------------------------------------
# Query params helper (fixes QueryParamsProxy error)
# ---------------------------------------------------------------------


def _get_query_params() -> dict:
    """
    Works on both new and old Streamlit versions.

    - On new versions, st.query_params is a dict-like object (no call).
    - On old versions, fall back to st.experimental_get_query_params().
    """
    try:
        # New API: property, not callable
        qp = st.query_params
    except Exception:
        # Old API: function
        qp = st.experimental_get_query_params()

    # Ensure we always return a plain dict
    return dict(qp)


# ---------------------------------------------------------------------
# Stripe Checkout helpers
# ---------------------------------------------------------------------


def start_checkout(plan: str, email: str):
    if not BACKEND_URL:
        st.error(
            "BACKEND_URL is not configured in Streamlit secrets or environment. "
            "Please set it so the app can talk to the backend."
        )
        return

    if not email:
        st.error("Please enter your email first. We need it to link your subscription.")
        return

    try:
        r = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan},
            timeout=20,
        )
    except requests.RequestException as e:
        st.error(f"Network error starting checkout: {e}")
        return

    if r.status_code != 200:
        try:
            payload = r.json()
            msg = payload.get("detail") or payload
        except Exception:
            msg = r.text
        st.error(f"Checkout failed ({r.status_code}): {msg}")
        return

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


def fetch_entitlements(email: str):
    """
    Call backend /me endpoint to see if this email has an active subscription.
    """
    if not BACKEND_URL or not email:
        return None

    try:
        r = requests.get(f"{BACKEND_URL}/me", params={"email": email}, timeout=15)
    except requests.RequestException:
        return None

    if r.status_code != 200:
        return None

    try:
        return r.json()
    except Exception:
        return None


# ---------------------------------------------------------------------
# Streamlit page
# ---------------------------------------------------------------------


def main():
    st.title("Billing & Plans")
    st.write("Choose a plan and manage your subscription.")

    _debug_backend_url()

    # --- Handle query params from Stripe redirect ---
    qp = _get_query_params()
    status = qp.get("status", [""])[0] if isinstance(qp.get("status"), list) else qp.get("status", "")
    session_id = (
        qp.get("session_id", [""])[0]
        if isinstance(qp.get("session_id"), list)
        else qp.get("session_id", "")
    )

    if status == "success":
        st.success("Payment successful—thanks! Your plan is now active.")
    elif status == "cancelled":
        st.info("Checkout was cancelled. You can restart it below anytime.")

    if session_id:
        st.caption(f"Stripe session: `{session_id}`")

    st.write("---")

    # --- Email entry ---
    st.subheader("Your email")
    st.caption("We use this to link your subscription and summaries.")

    email = st.text_input("Email address", placeholder="you@example.com")
    st.session_state["user_email"] = email.strip()

    entitlements = None
    if email:
        entitlements = fetch_entitlements(email.strip())
        if entitlements:
            if entitlements.get("has_active_subscription"):
                st.success(
                    f"Active subscription detected for **{email}** "
                    f"(plan: `{entitlements.get('plan')}`)"
                )
            else:
                st.warning(
                    f"No active subscription found for **{email}**. "
                    "You can start one below."
                )

    st.write("---")

    # --- Pricing cards ---
    st.subheader("Plans")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### Basic\n$9.99 / month")
        st.write(
            "- Upload up to **5 PDFs per month**\n"
            "- Standard AI clinical summaries\n"
            "- Email export"
        )
        if st.button("Choose Basic", key="btn_basic"):
            start_checkout("basic", email.strip())

    with col2:
        st.markdown("### Pro\n$19.99 / month")
        st.write(
            "- Upload up to **30 PDFs per month**\n"
            "- Faster, richer summaries (medication list, risk flags)\n"
            "- Priority email support"
        )
        if st.button("Choose Pro", key="btn_pro"):
            start_checkout("pro", email.strip())

    with col3:
        st.markdown("### Enterprise\n$39.99 / month")
        st.write(
            "- **Unlimited uploads**\n"
            "- Team accounts and shared templates\n"
            "- Premium support & integration help"
        )
        if st.button("Choose Enterprise", key="btn_enterprise"):
            start_checkout("enterprise", email.strip())

    st.write("---")
    st.caption(
        "After a successful checkout, you'll see your subscription reflected here "
        "and your upload limits will automatically adjust."
    )


if __name__ == "__main__":
    main()
