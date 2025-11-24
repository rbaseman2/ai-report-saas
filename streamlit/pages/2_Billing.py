# streamlit/pages/2_Billing.py

import os
import requests
import streamlit as st

# ---------------------------------------------------------
# Config
# ---------------------------------------------------------

# Read backend URL from environment (Render → Environment → BACKEND_URL)
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",  # safe default; change if needed
)

REQUEST_TIMEOUT = 30  # seconds


# ---------------------------------------------------------
# Helper functions
# ---------------------------------------------------------

def get_email() -> str:
    """Return the current billing email from session state."""
    return st.session_state.get("billing_email", "").strip()


def save_email(email: str) -> None:
    """Persist email in session state."""
    st.session_state["billing_email"] = email.strip()


def create_checkout_session(plan: str, email: str) -> None:
    """
    Call the FastAPI backend to create a Stripe Checkout session
    for the given plan and email.
    """
    if not BACKEND_URL:
        st.error(
            "The backend URL is not configured. Please set the `BACKEND_URL` "
            "environment variable on the frontend service."
        )
        return

    if not email:
        st.error("Please enter and save your email address above before choosing a plan.")
        return

    endpoint = f"{BACKEND_URL.rstrip('/')}/create-checkout-session"

    payload = {"plan": plan, "email": email}

    try:
        resp = requests.post(endpoint, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        st.error(f"Checkout failed: could not reach backend ({exc}).")
        return

    if resp.status_code != 200:
        # Show a concise error, but also the URL for debugging if needed
        st.error(
            f"Checkout failed ({resp.status_code}): {resp.text or 'Unexpected error from backend.'}"
        )
        return

    try:
        data = resp.json()
    except ValueError:
        st.error("Checkout failed: backend returned invalid JSON.")
        return

    checkout_url = data.get("checkout_url") or data.get("url")
    if not checkout_url:
        st.error("Checkout failed: backend did not return a checkout URL.")
        return

    st.success("Checkout session created. Your secure Stripe checkout will open in a new tab.")
    st.markdown(
        f'<a href="{checkout_url}" target="_blank">👉 Open Stripe checkout</a>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------
# UI
# ---------------------------------------------------------

st.set_page_config(page_title="Billing & Plans – AI Report", page_icon="💳")

st.title("Billing & Plans")
st.write(
    "Use this page to manage your subscription and upgrade your document summary limits."
)

# ---------------- Email section ----------------
st.subheader("Step 1 – Add your email")

st.caption(
    "We use this email to link your subscription, upload limits, and summaries. "
    "Use the same email address you’ll use at checkout."
)

current_email = get_email()
email_input = st.text_input("Email address", value=current_email, key="billing_email_input")

col_save, _ = st.columns([1, 3])
with col_save:
    if st.button("Save email"):
        if not email_input.strip():
            st.error("Please enter a valid email address.")
        else:
            save_email(email_input)
            st.success("Email saved. You can now choose a plan below.")


# ---------------- Plans section ----------------
st.subheader("Step 2 – Choose a plan")

st.caption(
    "Pick the plan that best fits your workload. You can upgrade later as your needs grow."
)

email_for_plans = get_email()

cols = st.columns(3)

# ----- Basic -----
with cols[0]:
    st.markdown("### Basic")
    st.write("**$9.99 / month**")
    st.markdown(
        """
- Upload up to **5 documents per month**
- Clear AI-generated summaries for clients and stakeholders
- Copy-paste summaries into emails, reports, and slide decks
        """
    )
    if st.button("Choose Basic", key="choose_basic"):
        create_checkout_session("basic", email_for_plans)

# ----- Pro -----
with cols[1]:
    st.markdown("### Pro")
    st.write("**$19.99 / month**")
    st.markdown(
        """
- Upload up to **30 documents per month**
- Deeper, more structured summaries (key points, risks, and action items)
- Priority email support
        """
    )
    if st.button("Choose Pro", key="choose_pro"):
        create_checkout_session("pro", email_for_plans)

# ----- Enterprise -----
with cols[2]:
    st.markdown("### Enterprise")
    st.write("**$39.99 / month**")
    st.markdown(
        """
- **Unlimited uploads** for your team
- Team accounts and shared templates
- Premium support & integration help
        """
    )
    if st.button("Choose Enterprise", key="choose_enterprise"):
        create_checkout_session("enterprise", email_for_plans)


# ---------------- Instructions after checkout ----------------
st.subheader("Step 3 – Start using your plan")

st.markdown(
    """
1. Go to the **Upload Data** page (link in the sidebar or below).  
2. Enter the **same email** you used here.  
3. Upload a report or paste your content.  
4. Click **Generate Business Summary** to create a client-ready summary.
"""
)

st.markdown("[Open Upload Data →](/Upload_Data)")
