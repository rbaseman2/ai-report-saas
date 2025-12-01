# streamlit/pages/2_Billing.py

import os
import requests
import streamlit as st

# ❗ MUST be the first Streamlit command on this page
st.set_page_config(page_title="Billing & Plans", page_icon="💳")

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _get_backend_url() -> str:
    """
    Resolve the backend URL from Streamlit secrets or environment.
    """
    # Try common secret keys
    for key in ("BACKEND_URL", "backend_url", "backendUrl"):
        try:
            if key in st.secrets:
                return str(st.secrets[key]).rstrip("/")
        except Exception:
            pass

    # Fallback to environment variable
    return os.getenv("BACKEND_URL", "").rstrip("/")


def check_subscription_status(email: str, backend_url: str):
    """
    Ask the backend for the current subscription status for this email.
    Returns a dict with: plan, max_documents, max_chars, and a status flag.
    """
    default = {
        "plan": "free",
        "max_documents": 5,
        "max_chars": 200_000,
        "status": "default",
    }

    if not backend_url:
        return {**default, "status": "backend_url_missing"}

    if not email:
        return default

    try:
        resp = requests.get(
            f"{backend_url}/subscription-status",
            params={"email": email},
            timeout=10,
        )
        if resp.status_code == 404:
            # No active subscription
            return {**default, "status": "no_subscription"}

        resp.raise_for_status()
        data = resp.json()

        return {
            "plan": data.get("plan", "free"),
            "max_documents": data.get("max_documents", 5),
            "max_chars": data.get("max_chars", 200_000),
            "status": "ok",
        }
    except Exception:
        # Fail gracefully: treat as free but mark status
        return {**default, "status": "error"}


def start_checkout(plan: str, email: str, backend_url: str):
    """
    Call the backend to create a Stripe Checkout session.
    """
    if not backend_url:
        st.error("Backend URL is not configured. Please contact support.")
        return

    if not email:
        st.error("Please enter your email address first.")
        return

    with st.spinner("Contacting billing system…"):
        try:
            resp = requests.post(
                f"{backend_url}/create-checkout-session",
                json={"plan": plan, "email": email},
                timeout=20,
            )
        except requests.RequestException as e:
            st.error(f"Network error starting checkout: {e}")
            return

    if resp.status_code != 200:
        # Try to show a helpful error
        try:
            payload = resp.json()
            msg = payload.get("detail") or payload
        except Exception:
            msg = resp.text
        st.error(f"Checkout failed ({resp.status_code}): {msg}")
        return

    data = resp.json() or {}
    url = data.get("url")
    if not url:
        st.error("Backend did not return a checkout URL.")
        return

    st.success("Redirecting you to secure checkout…")
    # Auto redirect in same tab with meta-refresh
    st.markdown(
        f"""
        <meta http-equiv="refresh" content="0; url={url}">
        <p>If you are not redirected automatically, <a href="{url}">click here</a>.</p>
        """,
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------
# Page layout
# ------------------------------------------------------------

BACKEND_URL = _get_backend_url()

st.title("Billing & Subscription")

if not BACKEND_URL:
    st.error("Backend URL is not configured in this environment.")
    st.stop()

# Handle return from Stripe Checkout (status + plan in query params)
qs = st.query_params
status_param = qs.get("status", "")
plan_param = qs.get("plan", "")
if isinstance(status_param, list):
    status_param = status_param[0]
if isinstance(plan_param, list):
    plan_param = plan_param[0]

if status_param == "success":
    st.success(
        "Payment successful. Your subscription is now active. "
        "You can start uploading reports from the **Upload Data** tab."
    )
elif status_param == "cancelled":
    st.info("Checkout was cancelled. You have not been charged.")

# Clear query params so the message doesn’t keep reappearing on reload
st.experimental_set_query_params()

st.write(
    "Choose a plan that matches how often you need to summarize reports. "
    "You can upgrade at any time as your workload grows."
)

# ------------------------------------------------------------
# Email capture
# ------------------------------------------------------------

st.markdown("### Your billing email")

default_email = st.session_state.get("user_email", "")
email = st.text_input(
    "We use this email to link your subscription with your account.",
    value=default_email,
    placeholder="you@company.com",
)

if email and email != default_email:
    st.session_state["user_email"] = email

# ------------------------------------------------------------
# Current plan card
# ------------------------------------------------------------

current_sub = check_subscription_status(email, BACKEND_URL) if email else None

with st.container(border=True):
    st.subheader("Current plan")

    if not email:
        st.caption("Enter your email to see your current subscription status.")
        st.markdown("**Status:** Free (no subscription found)")
    else:
        plan_label = current_sub["plan"].capitalize()
        st.markdown(f"**Plan:** {plan_label}")

        st.caption(
            f"Included usage: up to **{current_sub['max_documents']}** documents "
            f"and roughly **{current_sub['max_chars']:,}** characters per billing period."
        )

        if current_sub["status"] == "no_subscription":
            st.info(
                "We didn’t find an active subscription for this email. "
                "You are currently on the Free tier."
            )
        elif current_sub["status"] == "error":
            st.warning(
                "We couldn’t reach the billing system. "
                "For now, we’re treating you as on the Free tier."
            )

    st.caption(
        "Your plan controls how many reports you can upload and the maximum length "
        "we can summarize each month."
    )

st.divider()

# ------------------------------------------------------------
# Plan comparison grid
# ------------------------------------------------------------

st.subheader("Compare plans")

cols = st.columns(3)

plans_ui = [
    {
        "id": "basic",
        "name": "Basic",
        "price": "$9.99 / month",
        "ideal_for": "Solo professionals & light usage",
        "features": [
            "Up to 20 reports / month",
            "Up to 400k characters / month",
            "Executive summaries + key insights",
        ],
    },
    {
        "id": "pro",
        "name": "Pro",
        "price": "$19.99 / month",
        "ideal_for": "Consultants & small teams",
        "features": [
            "Up to 75 reports / month",
            "Up to 1.5M characters / month",
            "Action items, risks, and opportunity insights",
        ],
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price": "$49.99 / month",
        "ideal_for": "Teams with heavy reporting needs",
        "features": [
            "Up to 250 reports / month",
            "Up to 5M characters / month",
            "Priority processing & extended history",
        ],
    },
]

for col, plan in zip(cols, plans_ui):
    with col:
        st.markdown(f"### {plan['name']}")
        st.markdown(f"**{plan['price']}**")
        st.caption(plan["ideal_for"])

        for feat in plan["features"]:
            st.markdown(f"- {feat}")

        if current_sub and current_sub["plan"] == plan["id"]:
            st.success("Current plan")
            disabled = True
            label = "Selected"
        else:
            disabled = False
            label = f"Choose {plan['name']}"

        if st.button(label, key=f"btn_{plan['id']}", disabled=disabled):
            if not email:
                st.error("Please enter your email above before choosing a plan.")
            else:
                start_checkout(plan["id"], email, BACKEND_URL)

st.info(
    "After you subscribe, return to the **Upload Data** tab to start generating "
    "client-ready summaries from your reports."
)
