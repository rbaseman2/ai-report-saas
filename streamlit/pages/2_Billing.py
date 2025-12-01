import os
from typing import Dict, Tuple

import requests
import streamlit as st

# --------------------------------------------------------------------
# Page config – must be the FIRST Streamlit call
# --------------------------------------------------------------------
st.set_page_config(page_title="Billing & Plans – AI Report", page_icon="💳")

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",  # <-- keep your actual backend URL here
).rstrip("/")

DEFAULT_LIMITS = {
    "max_documents": 5,
    "max_chars": 200_000,
}

PLAN_LABELS = {
    "free": "Free plan",
    "basic": "Basic",
    "pro": "Pro",
    "enterprise": "Enterprise",
}


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def _qp(name: str):
    """Safe helper to read a single query param value."""
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def fetch_subscription(email: str) -> Tuple[str, Dict[str, int]]:
    """
    Call the backend to get the current subscription for this email.

    Returns (plan, limits_dict).
    On any error, we gracefully fall back to the Free plan.
    """
    if not email:
        return "free", DEFAULT_LIMITS.copy()

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=20,
        )
    except Exception as e:
        # Backend unreachable (cold start, network, etc.)
        st.warning(
            "We couldn’t reach the billing server just now, "
            "so we’re treating you as on the Free plan for this session."
        )
        st.caption(f"Technical details: {e}")
        return "free", DEFAULT_LIMITS.copy()

    # No active subscription for this email -> treat as Free, but not an error
    if resp.status_code == 404:
        return "free", DEFAULT_LIMITS.copy()

    # Any other HTTP error
    try:
        resp.raise_for_status()
    except Exception as e:
        st.error(f"Error while checking subscription: {e}")
        return "free", DEFAULT_LIMITS.copy()

    data = resp.json() or {}
    plan = data.get("plan", "free")
    limits = {
        "max_documents": data.get("max_documents", DEFAULT_LIMITS["max_documents"]),
        "max_chars": data.get("max_chars", DEFAULT_LIMITS["max_chars"]),
    }
    return plan, limits


def create_checkout_session(email: str, plan: str) -> str:
    """
    Ask the backend to create a Stripe Checkout session and
    return the redirect URL.
    """
    payload = {"plan": plan, "email": email}

    resp = requests.post(
        f"{BACKEND_URL}/create-checkout-session",
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    url = data.get("checkout_url")
    if not url:
        raise RuntimeError("Backend response did not include 'checkout_url'")
    return url


# --------------------------------------------------------------------
# Handle return from Stripe (status & session_id query params)
# --------------------------------------------------------------------
status = _qp("status")      # "success", "canceled", or None
session_id = _qp("session_id")

if "subscription_plan" not in st.session_state:
    st.session_state["subscription_plan"] = "free"
if "limits" not in st.session_state:
    st.session_state["limits"] = DEFAULT_LIMITS.copy()

if status == "success":
    # We just came back from Stripe. If we know the user email, try to refresh.
    email = st.session_state.get("user_email")
    if email:
        plan, limits = fetch_subscription(email)
        st.session_state["subscription_plan"] = plan
        st.session_state["limits"] = limits
        st.success(
            "Checkout complete! We’ve refreshed your subscription "
            f"for **{email}** (current plan: **{PLAN_LABELS.get(plan, plan)}**)."
        )
    else:
        st.info(
            "Checkout complete! Enter the same email you used at checkout "
            "and click **Save email & check plan** to refresh your limits."
        )

elif status == "canceled":
    st.info("Your checkout was canceled. You’re still on your current plan.")


# --------------------------------------------------------------------
# UI – Step 1: Add your email
# --------------------------------------------------------------------
st.title("Billing & Plans")

st.write(
    "Use this page to manage your subscription and upgrade your "
    "document summary limits. Use the same email address at checkout."
)

st.subheader("Step 1 – Add your email")

default_email = st.session_state.get("user_email", "")
email = st.text_input("Email address", value=default_email, placeholder="you@example.com")

col_save, _ = st.columns([1, 3])
with col_save:
    if st.button("Save email & check plan", type="primary"):
        if not email:
            st.error("Please enter an email address first.")
        else:
            st.session_state["user_email"] = email

            plan, limits = fetch_subscription(email)
            st.session_state["subscription_plan"] = plan
            st.session_state["limits"] = limits

            label = PLAN_LABELS.get(plan, plan)
            if plan == "free":
                st.info(
                    f"We haven’t detected an active subscription for **{email}**. "
                    "You’re currently on the **Free plan**."
                )
            else:
                st.success(
                    f"Subscription found for **{email}**. "
                    f"Current plan: **{label}**."
                )

# Show current status
current_plan = st.session_state.get("subscription_plan", "free")
st.caption(
    f"Status: **{PLAN_LABELS.get(current_plan, current_plan)}**. "
    "You can upgrade in Step 2 below."
)


# --------------------------------------------------------------------
# UI – Step 2: Choose a plan
# --------------------------------------------------------------------
st.subheader("Step 2 – Choose a plan")
st.write("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

if not email:
    st.info("Enter and save your email in Step 1 before choosing a plan.")

col_basic, col_pro, col_ent = st.columns(3)

with col_basic:
    st.markdown("### Basic")
    st.write("$9.99 / month")
    st.write("- Upload up to **5 documents per month**")
    st.write("- Clear AI-generated summaries for clients and stakeholders")
    st.write("- Copy-paste into emails, reports, and slide decks")

    disabled = not email
    if st.button("Choose Basic", disabled=disabled):
        try:
            checkout_url = create_checkout_session(email, "basic")
            st.success("Redirecting you to secure checkout…")
            st.markdown(
                f"<meta http-equiv='refresh' content='0; url={checkout_url}'>",
                unsafe_allow_html=True,
            )
            st.markdown(f"[Click here if you’re not redirected]({checkout_url})")
        except Exception as e:
            st.error(f"Checkout failed: {e}")

with col_pro:
    st.markdown("### Pro")
    st.write("$19.99 / month")
    st.write("- Upload up to **30 documents per month**")
    st.write("- Deeper, more structured summaries (key points, risks, and action items)")
    st.write("- Priority email support")

    disabled = not email
    if st.button("Choose Pro", disabled=disabled):
        try:
            checkout_url = create_checkout_session(email, "pro")
            st.success("Redirecting you to secure checkout…")
            st.markdown(
                f"<meta http-equiv='refresh' content='0; url={checkout_url}'>",
                unsafe_allow_html=True,
            )
            st.markdown(f"[Click here if you’re not redirected]({checkout_url})")
        except Exception as e:
            st.error(f"Checkout failed: {e}")

with col_ent:
    st.markdown("### Enterprise")
    st.write("$39.99 / month")
    st.write("- **Unlimited uploads** for your team")
    st.write("- Team accounts and shared templates")
    st.write("- Premium support & integration help")

    disabled = not email
    if st.button("Choose Enterprise", disabled=disabled):
        try:
            checkout_url = create_checkout_session(email, "enterprise")
            st.success("Redirecting you to secure checkout…")
            st.markdown(
                f"<meta http-equiv='refresh' content='0; url={checkout_url}'>",
                unsafe_allow_html=True,
            )
            st.markdown(f"[Click here if you’re not redirected]({checkout_url})")
        except Exception as e:
            st.error(f"Checkout failed: {e}")


# --------------------------------------------------------------------
# UI – Step 3: Start using your plan
# --------------------------------------------------------------------
st.subheader("Step 3 – Start using your plan")
st.markdown(
    """
1. Go to the **Upload Data** page (link in the sidebar on the left).  
2. Enter the **same email** you used here.  
3. Upload a report or paste your content.  
4. Click **Generate Business Summary** to create a client-ready summary.
"""
)
