import os
import requests
import streamlit as st

# -------------------------------------------------------------------
# Page config (must be first Streamlit call)
# -------------------------------------------------------------------
st.set_page_config(
    page_title="Billing & Plans – AI Report",
    page_icon="💳",
    layout="wide",
)

# Backend URL – set in Render as BACKEND_URL (falls back to localhost for dev)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

st.title("Billing & Plans")
st.caption(
    "Use this page to manage your subscription and upgrade your document summary limits."
)

# Optional: show which backend we're talking to (helps when debugging)
st.caption(f"Using backend: {BACKEND_URL}")

# -------------------------------------------------------------------
# Query params (e.g. after redirect back from Stripe)
# -------------------------------------------------------------------
qp = st.query_params
status = qp.get("status")
# st.query_params values are lists; normalize to a single string
if isinstance(status, list):
    status = status[0]

if status == "success":
    st.success("Your subscription was completed successfully.")
elif status == "cancelled":
    st.info("Checkout cancelled. You can start again at any time.")
elif status == "error":
    st.error("There was a problem with checkout. Please try again or contact support.")

st.markdown("---")

# -------------------------------------------------------------------
# Email capture
# -------------------------------------------------------------------
st.markdown("### Your email")
st.caption(
    "We use this email to link your subscription, upload limits, and summaries. "
    "Use the same address you enter on the Stripe checkout page."
)

default_email = st.session_state.get("user_email", "")
email = st.text_input("Email address", value=default_email or "", key="billing_email")

if st.button("Save email"):
    if not email:
        st.warning("Please enter an email address first.")
    else:
        st.session_state["user_email"] = email
        st.success("Email saved. You can now choose a plan below to continue to checkout.")

st.markdown("---")

# -------------------------------------------------------------------
# Helper: start checkout via backend
# -------------------------------------------------------------------
def start_checkout(plan: str) -> None:
    """
    Call the FastAPI backend to create a Stripe Checkout Session
    and return a link the user can click.

    plan: "basic" | "pro" | "enterprise"
    """
    if not email:
        st.warning("Please enter and save your email before choosing a plan.")
        return

    payload = {"email": email, "plan": plan}

    try:
        with st.spinner("Contacting secure payment server…"):
            resp = requests.post(
                f"{BACKEND_URL}/create-checkout-session",
                json=payload,
                timeout=60,  # give Render time to wake the backend
            )
        resp.raise_for_status()
        data = resp.json()
        checkout_url = data.get("checkout_url")

        if not checkout_url:
            st.error("Backend did not return a checkout URL. Please try again in a moment.")
            return

        st.success("Checkout created. Click below to continue securely on Stripe:")
        st.markdown(
            f"[➡️ Open secure checkout]({checkout_url})",
            unsafe_allow_html=False,
        )

    except requests.exceptions.Timeout:
        st.error(
            "The request to the payment server timed out. "
            "If your backend was asleep, please wait a few seconds and try again."
        )
    except Exception as exc:
        st.error(f"Checkout failed: {exc}")

# -------------------------------------------------------------------
# Plan cards
# -------------------------------------------------------------------
st.markdown("### Plans")

col_basic, col_pro, col_ent = st.columns(3)

with col_basic:
    st.subheader("Basic")
    st.caption("$9.99 / month")
    st.markdown(
        """
- Upload up to **5 documents per month**  
- Clear AI-generated summaries for clients and stakeholders  
- Copy-paste summaries into emails, reports, and slide decks  
        """
    )
    if st.button("Choose Basic"):
        start_checkout("basic")

with col_pro:
    st.subheader("Pro")
    st.caption("$19.99 / month")
    st.markdown(
        """
- Upload up to **30 documents per month**  
- Deeper, more structured summaries (key points, risks, and action items)  
- Priority email support  
        """
    )
    if st.button("Choose Pro"):
        start_checkout("pro")

with col_ent:
    st.subheader("Enterprise")
    st.caption("$39.99 / month")
    st.markdown(
        """
- **Unlimited uploads** for your team  
- Team accounts and shared templates  
- Premium support & integration help  
        """
    )
    if st.button("Choose Enterprise"):
        start_checkout("enterprise")

st.markdown("---")

st.caption(
    "After a successful checkout, your plan will be updated automatically and your upload "
    "limits will adjust on the **Upload Data** page (once enforced in the backend)."
)
