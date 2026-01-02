"""
streamlit/2_Billing.py

Billing page:
- Save billing email
- Check current plan/status (from backend /subscription-status)
- Choose plan -> backend /create-checkout-session -> redirect to Stripe Checkout
"""
from __future__ import annotations

import os
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Billing & Subscription", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL") or os.getenv("BACKEND_API_URL") or ""
if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set.")
    st.stop()

st.title("Billing & Subscription")

# -------------------------
# Step 1 — Email
# -------------------------
email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.get("billing_email", ""),
)

if st.button("Save email & check current plan"):
    if not email:
        st.warning("Please enter an email address.")
    else:
        st.session_state["billing_email"] = email
        try:
            r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": email}, timeout=30)
            r.raise_for_status()
            data = r.json()

            # Backend returns BOTH:
            # - plan/status (what this page expects)
            # - current_plan/subscription_status (extra)
            plan = data.get("plan") or data.get("current_plan") or "none"
            status = data.get("status") or data.get("subscription_status") or "none"

            st.session_state["current_plan"] = plan
            st.session_state["subscription_status"] = status

            st.success(f"Status: {status} | Current plan: {plan}")
        except requests.HTTPError as e:
            st.error(f"Could not check subscription. Backend error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            st.error(f"Could not check subscription: {e}")

status = st.session_state.get("subscription_status", "none")
plan = st.session_state.get("current_plan", "none")
st.info(f"Status: {status} | Current plan: {plan}")

st.divider()

# -------------------------
# Step 2 — Plans
# -------------------------
st.subheader("Step 2 — Compare plans & upgrade")
st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

def start_checkout(selected_plan: str):
    if not st.session_state.get("billing_email"):
        st.warning("Enter and save your billing email above before selecting a plan.")
        return

    payload = {"email": st.session_state["billing_email"], "plan": selected_plan}
    try:
        r = requests.post(f"{BACKEND_URL}/create-checkout-session", json=payload, timeout=30)
        r.raise_for_status()
        j = r.json()
        checkout_url = j.get("checkout_url") or j.get("url")
        if not checkout_url:
            st.error("Checkout URL was not returned by backend.")
            return

        # Redirect
        st.markdown(f"[Click here if you are not redirected automatically]({checkout_url})")
        components.html(f"""<script>window.location.href = \"{checkout_url}\";</script>""", height=0)
except requests.HTTPError as e:
        st.error(f"Could not start checkout. Backend error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        st.error(f"Could not start checkout: {e}")

c1, c2, c3 = st.columns(3)

def plan_card(col, title: str, price: str, bullets: list[str], plan_key: str):
    with col:
        st.markdown(f"### {title}")
        st.markdown(f"**{price} / month**")
        for b in bullets:
            st.write(f"• {b}")
        st.button(f"Choose {title}", on_click=start_checkout, args=(plan_key,), use_container_width=True)

plan_card(
    c1,
    "Basic",
    "$9.99",
    [
        "Up to 20 reports / month",
        "Up to 400k characters / month",
        "Executive summaries + key insights",
    ],
    "basic",
)

plan_card(
    c2,
    "Pro",
    "$19.99",
    [
        "Up to 75 reports / month",
        "Up to 1.5M characters / month",
        "Action items, risks, and opportunity insights",
    ],
    "pro",
)

plan_card(
    c3,
    "Enterprise",
    "$39.99",
    [
        "Up to 250 reports / month",
        "Up to 5M characters / month",
        "Team accounts, shared templates, & premium support",
    ],
    "enterprise",
)

st.caption("Coupons/promo codes are entered on the Stripe Checkout page (they will appear if enabled in your Stripe settings).")
