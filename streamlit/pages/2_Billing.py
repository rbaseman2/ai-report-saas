import os
import requests
import streamlit as st

# ----------------------------
# Page config
# ----------------------------
st.set_page_config(
    page_title="Billing & Subscription",
    layout="wide"
)

st.title("Billing & Subscription")

# Optional build marker (helps detect stale deployments)
st.caption("Billing build: 2025-12-12 v9")

# ----------------------------
# Backend configuration
# ----------------------------
BACKEND_URL = os.getenv("BACKEND_URL")
if not BACKEND_URL:
    st.error("BACKEND_URL is not configured.")
    st.stop()

# ----------------------------
# Handle redirect from Stripe
# ----------------------------
query_params = st.query_params
if query_params.get("status") == "success":
    st.success("Payment successful! Your subscription is now active.")

# ----------------------------
# Session state defaults
# ----------------------------
if "billing_email" not in st.session_state:
    st.session_state.billing_email = ""

if "current_plan" not in st.session_state:
    st.session_state.current_plan = None

if "subscription_status" not in st.session_state:
    st.session_state.subscription_status = "none"

# ----------------------------
# STEP 1 – Enter email
# ----------------------------
st.subheader("Step 1 – Enter your email")

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.billing_email,
    placeholder="you@example.com"
)

def check_subscription():
    if not email:
        st.warning("Please enter an email address.")
        return

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=15
        )
    except Exception as e:
        st.error(f"Error contacting backend: {e}")
        return

    if resp.status_code != 200:
        st.error(f"Unexpected response from billing backend ({resp.status_code}).")
        return

    data = resp.json() or {}

    status = data.get("status") or "none"
    plan = data.get("plan")  # may be None

    st.session_state.billing_email = email
    st.session_state.subscription_status = status
    st.session_state.current_plan = plan

    if status in ("active", "trialing"):
        plan_label = (plan or "unknown").capitalize()
        st.success(f"Active subscription found: {plan_label} (status: {status})")
    else:
        st.info("No active subscription found for this email.")

st.button("Save email & check current plan", on_click=check_subscription)

st.write(f"**Status:** {st.session_state.subscription_status}")

st.divider()

# ----------------------------
# STEP 2 – Compare plans
# ----------------------------
st.subheader("Step 2 – Compare plans & upgrade")
st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

cols = st.columns(3)

PLANS = [
    {
        "key": "basic",
        "title": "Basic",
        "price": "$9.99 / month",
        "features": [
            "Up to 20 reports / month",
            "Up to 400k characters / month",
            "Executive summaries + key insights",
        ],
    },
    {
        "key": "pro",
        "title": "Pro",
        "price": "$19.99 / month",
        "features": [
            "Up to 75 reports / month",
            "Up to 1.5M characters / month",
            "Action items, risks, opportunity insights",
        ],
    },
    {
        "key": "enterprise",
        "title": "Enterprise",
        "price": "$39.99 / month",
        "features": [
            "Up to 250 reports / month",
            "Up to 5M characters / month",
            "Team accounts, shared templates",
            "Premium support",
        ],
    },
]

def start_checkout(plan_key: str):
    if not st.session_state.billing_email:
        st.warning("Please enter and save your email first.")
        return

    payload = {
        "plan": plan_key,
        "email": st.session_state.billing_email,
    }

    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json=payload,
            timeout=15,
        )
    except Exception as e:
        st.error(f"Error contacting billing backend: {e}")
        return

    if resp.status_code != 200:
        st.error("Unexpected response from billing backend.")
        return

    data = resp.json() or {}
    checkout_url = data.get("url")

    if not checkout_url:
        st.error("Checkout URL was not returned by backend.")
        return

    st.markdown(f"[Proceed to secure checkout]({checkout_url})", unsafe_allow_html=True)

for col, plan in zip(cols, PLANS):
    with col:
        st.markdown(f"### {plan['title']}")
        st.markdown(plan["price"])
        for f in plan["features"]:
            st.markdown(f"- {f}")

        is_current = (
            st.session_state.current_plan == plan["key"]
            and st.session_state.subscription_status in ("active", "trialing")
        )

        if is_current:
            st.success("Current plan")
        else:
            st.button(
                f"Choose {plan['title']}",
                key=f"choose_{plan['key']}",
                on_click=start_checkout,
                args=(plan["key"],),
            )
