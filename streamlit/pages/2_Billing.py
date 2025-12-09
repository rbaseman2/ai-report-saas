import os
import requests
import streamlit as st

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

# Read backend URL from an environment variable on Render
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",
).rstrip("/")

# Plan tooltips / descriptions (for display only)
PLAN_FEATURES = {
    "basic": {
        "label": "Basic",
        "price": "$9.99 / month",
        "bullets": [
            "Up to 20 reports / month",
            "Up to 400k characters / month",
            "Executive summaries + key insights",
        ],
    },
    "pro": {
        "label": "Pro",
        "price": "$19.99 / month",
        "bullets": [
            "Up to 75 reports / month",
            "Up to 1.5M characters / month",
            "Action items, risks, and opportunity insights",
        ],
    },
    "enterprise": {
        "label": "Enterprise",
        "price": "$39.99 / month",
        "bullets": [
            "Up to 250 reports / month",
            "Up to 5M characters / month",
            "Team accounts, shared templates, & premium support",
        ],
    },
}

# ------------------------------------------------------------------
# Helpers to talk to backend
# ------------------------------------------------------------------


def get_subscription_status(email: str | None) -> dict | None:
    """
    Call backend /subscription-status?email=... to show the current plan.
    Returns a dict or None if email is empty or request fails.
    """
    if not email:
        return None

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def start_checkout(email: str, plan: str) -> None:
    """
    Call backend /create-checkout-session to start Stripe Checkout.

    We ONLY send email + plan. Coupon entry will happen on the Stripe
    checkout page itself (via allow_promotion_codes=True on the backend).
    """
    payload = {"plan": plan, "email": email}

    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json=payload,
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Network error starting checkout: {exc}")
        return

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text
        st.error(f"Checkout error: {detail}")
        return

    data = resp.json()
    checkout_url = data.get("checkout_url")
    if not checkout_url:
        st.error("Backend did not return a checkout URL.")
        return

    # Redirect in the browser
    st.session_state["redirect_url"] = checkout_url
    st.experimental_rerun()


# ------------------------------------------------------------------
# Streamlit page layout
# ------------------------------------------------------------------

st.set_page_config(page_title="Billing & Subscription", page_icon="💳")

st.title("Billing & Subscription")

st.markdown(
    """
Use this page to manage your AI Report Assistant subscription.

1. **Enter your billing email** so we can look up your subscription.
2. **Choose a plan** to start a Stripe checkout session.

You can update or cancel your subscription any time from your Stripe receipt.
"""
)

# Initialise session state
if "billing_email" not in st.session_state:
    st.session_state["billing_email"] = ""

# ------------------------------------------------------------------
# Step 1 – Email
# ------------------------------------------------------------------

st.markdown("### Step 1 – Enter your email")

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state["billing_email"],
    placeholder="you@example.com",
)

col_save, col_status = st.columns([1, 3])

with col_save:
    if st.button("Save email & check current plan"):
        st.session_state["billing_email"] = email

with col_status:
    if st.session_state["billing_email"]:
        status = get_subscription_status(st.session_state["billing_email"])
        if status is None:
            st.info("No active subscription found for this email.")
        else:
            plan = status.get("plan", "unknown").title()
            renewal = status.get("current_period_end_readable", "N/A")
            st.success(
                f"Active subscription: **{plan}** plan. "
                f"Renews on **{renewal}**."
            )
    else:
        st.caption("Enter your email and click **Save** to see your status.")

st.markdown("---")

# ------------------------------------------------------------------
# Step 2 – Plan selection
# ------------------------------------------------------------------

st.markdown("### Step 2 – Compare plans & upgrade")

st.write("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

col_basic, col_pro, col_ent = st.columns(3)

# Basic
with col_basic:
    st.markdown("#### Basic\n$9.99 / month")
    st.write(
        "- Up to 20 reports / month\n"
        "- Up to 400k characters / month\n"
        "- Executive summaries + key insights"
    )
    if st.button("Choose Basic"):
        if not st.session_state["billing_email"]:
            st.error("Enter and save your billing email in Step 1 first.")
        else:
            start_checkout(st.session_state["billing_email"], "basic")

# Pro
with col_pro:
    st.markdown("#### Pro\n$19.99 / month")
    st.write(
        "- Up to 75 reports / month\n"
        "- Up to 1.5M characters / month\n"
        "- Action items, risks, and opportunity insights"
    )
    if st.button("Choose Pro"):
        if not st.session_state["billing_email"]:
            st.error("Enter and save your billing email in Step 1 first.")
        else:
            start_checkout(st.session_state["billing_email"], "pro")

# Enterprise
with col_ent:
    st.markdown("#### Enterprise\n$39.99 / month")
    st.write(
        "- Up to 250 reports / month\n"
        "- Up to 5M characters / month\n"
        "- Team accounts, shared templates, & premium support"
    )
    if st.button("Choose Enterprise"):
        if not st.session_state["billing_email"]:
            st.error("Enter and save your billing email in Step 1 first.")
        else:
            start_checkout(st.session_state["billing_email"], "enterprise")

st.markdown("---")
st.caption(
    "After you subscribe, return to the **Upload Data** tab to start generating "
    "client-ready summaries from your reports."
)
