# streamlit/pages/2_Billing.py

import os
import textwrap
from typing import Dict, Any

import requests
import streamlit as st


# --- Config -----------------------------------------------------------------

# Backend URL comes from environment (Render "Environment" tab)
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",  # fallback for local dev
)

PLAN_DISPLAY = {
    "basic": {
        "name": "Basic",
        "price": "$9.99 / month",
        "bullets": [
            "Upload up to **5 documents per month**",
            "Clear AI-generated summaries for clients and stakeholders",
            "Copy-paste summaries into emails, reports, and slide decks",
        ],
    },
    "pro": {
        "name": "Pro",
        "price": "$19.99 / month",
        "bullets": [
            "Upload up to **30 documents per month**",
            "Deeper, more structured summaries (key points, risks, and action items)",
            "Priority email support",
        ],
    },
    "enterprise": {
        "name": "Enterprise",
        "price": "$39.99 / month",
        "bullets": [
            "**Unlimited uploads** for your team",
            "Team accounts and shared templates",
            "Premium support & integration help",
        ],
    },
}


# --- Helpers -----------------------------------------------------------------


def get_query_params() -> Dict[str, Any]:
    """Compat helper for older/newer Streamlit versions."""
    if hasattr(st, "query_params"):
        return st.query_params  # type: ignore[attr-defined]
    return st.experimental_get_query_params()


def redirect_to(url: str) -> None:
    """Client-side redirect."""
    st.write(
        f"<script>window.location.href = {url!r};</script>",
        unsafe_allow_html=True,
    )


def call_backend_create_session(plan: str, email: str) -> None:
    """Call backend to create Stripe Checkout session and redirect browser."""
    if not BACKEND_URL:
        st.error("Backend URL is not configured on the server.")
        return

    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan, "email": email},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        st.error(f"Checkout failed: {exc}")
        return

    data = resp.json()
    checkout_url = data.get("checkout_url") or data.get("url")
    if not checkout_url:
        st.error("Checkout failed: backend did not return a checkout URL.")
        return

    redirect_to(checkout_url)


# --- Page layout -------------------------------------------------------------

st.set_page_config(page_title="Billing & Plans", page_icon="💳")
st.title("Billing & Plans")
st.write(
    "Use this page to manage your subscription and upgrade your document "
    "summary limits."
)

# Read query params from Stripe redirect (e.g. ?status=success&session_id=...)
params = get_query_params()
status_param = params.get("status", [None])[0] if "status" in params else None
session_id = params.get("session_id", [None])[0] if "session_id" in params else None

# --- Post-checkout states ----------------------------------------------------

if status_param == "success":
    st.success(
        "✅ Your checkout completed successfully. "
        "You can now start using your plan on the **Upload Data** page."
    )
    st.markdown(
        "[➡️ Go to the Upload Data page](/Upload_Data)",
        unsafe_allow_html=True,
    )
    st.info(
        "There’s no need to re-enter your email or choose a plan again for this "
        "session. Just head over to **Upload Data** and use the same email you "
        "just used at checkout."
    )
    # We intentionally stop here so the user doesn't see the Step 1 / Step 2
    # form again right after a successful payment.
    st.stop()
elif status_param == "cancel":
    st.warning(
        "You cancelled the checkout before completing payment. "
        "If that was intentional, no charges were made. You can choose a plan "
        "again below."
    )
elif status_param == "error":
    st.error(
        "We couldn’t confirm your checkout. "
        "Please choose a plan again or contact support if this keeps happening."
    )

# --- Step 1 – Email ---------------------------------------------------------

st.subheader("Step 1 – Add your email")

st.caption(
    "We use this email to link your subscription, upload limits, and summaries. "
    "Use the same email address you’ll use at checkout."
)

if "billing_email" not in st.session_state:
    st.session_state.billing_email = ""

email = st.text_input(
    "Email address",
    value=st.session_state.billing_email,
    placeholder="you@example.com",
)

save_email_clicked = st.button("Save email", type="primary")

if save_email_clicked:
    if not email:
        st.error("Please enter an email address first.")
    else:
        st.session_state.billing_email = email
        st.success("Email saved. You can now choose a plan below.")

st.markdown("---")

# --- Step 2 – Choose a plan --------------------------------------------------

st.subheader("Step 2 – Choose a plan")
st.caption(
    "Pick the plan that best fits your workload. You can upgrade later as your "
    "needs grow."
)

if not st.session_state.billing_email:
    st.info("Enter and save your email above before choosing a plan.")

cols = st.columns(3)

for col, plan_key in zip(cols, ["basic", "pro", "enterprise"]):
    plan = PLAN_DISPLAY[plan_key]
    with col:
        st.markdown(f"### {plan['name']}")
        st.markdown(plan["price"])
        st.markdown(
            "\n".join(f"- {bullet}" for bullet in plan["bullets"])
        )
        disabled = not bool(st.session_state.billing_email)
        if st.button(
            f"Choose {plan['name']}",
            key=f"choose_{plan_key}",
            disabled=disabled,
        ):
            if not st.session_state.billing_email:
                st.error("Please save your email in Step 1 before choosing a plan.")
            else:
                call_backend_create_session(plan_key, st.session_state.billing_email)

st.markdown("---")

# --- Step 3 – Start using your plan -----------------------------------------

st.subheader("Step 3 – Start using your plan")
st.markdown(
    textwrap.dedent(
        """
        1. Go to the **Upload Data** page (link in the sidebar or below).
        2. Enter the **same email** you used here.
        3. Upload a report or paste your content.
        4. Click **Generate Business Summary** to create a client-ready summary.

        [Open Upload Data page →](/Upload_Data)
        """
    )
)
