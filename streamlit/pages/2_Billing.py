import os
from typing import Optional

import requests
import streamlit as st
import streamlit.components.v1 as components

# ---------- Config ----------

st.set_page_config(page_title="Billing & Subscription", page_icon="💳")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    st.error(
        "BACKEND_URL environment variable is not set on the Streamlit service. "
        "Set it to your backend URL (e.g. https://ai-report-backend-ubrx.onrender.com)."
    )
    st.stop()


def open_in_new_tab(url: str):
    """Client-side redirect to the Stripe checkout page."""
    components.html(
        f"<script>window.location.href = '{url}';</script>",
        height=0,
    )


def get_subscription_status(email: str) -> Optional[dict]:
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=10,
        )
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    return resp.json()


def start_checkout(email: str, plan: str):
    """Call backend to create a Stripe Checkout session."""
    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"email": email, "plan": plan},
            timeout=20,
        )
    except requests.RequestException as exc:
        st.error(f"Network error contacting billing backend: {exc}")
        return

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", "Unknown error")
        except Exception:
            detail = resp.text or "Unknown error"
        st.error(f"Checkout error: {detail}")
        return

    data = resp.json()
    checkout_url = data.get("checkout_url")
    if not checkout_url:
        st.error("Backend did not return a checkout URL.")
        return

    open_in_new_tab(checkout_url)


# ---------- UI ----------

st.title("Billing & Subscription")

st.markdown("### Step 1 – Enter your email")

if "billing_email" not in st.session_state:
    st.session_state["billing_email"] = ""

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state["billing_email"],
)

col_save, _ = st.columns([1, 3])
with col_save:
    if st.button("Save email & check current plan"):
        st.session_state["billing_email"] = email.strip()
        if not st.session_state["billing_email"]:
            st.error("Please enter a valid email first.")
        else:
            status = get_subscription_status(st.session_state["billing_email"])
            if not status:
                st.info("No active subscription found for this email.")
            else:
                sub_status = status.get("status", "none")
                plan = status.get("plan") or "Unknown plan"
                if sub_status in ("active", "trialing"):
                    st.success(
                        f"Active subscription: **{plan}** "
                        f"(status: {sub_status})."
                    )
                else:
                    st.info(
                        f"No active subscription found for this email "
                        f"(last status: {sub_status})."
                    )

st.markdown("---")

st.markdown("### Step 2 – Compare plans & upgrade")
st.write(
    "Pick the plan that best fits your workload. "
    "You can upgrade later as your needs grow."
)

col_basic, col_pro, col_ent = st.columns(3)

with col_basic:
    st.markdown("#### Basic\n$9.99 / month")
    st.write(
        "- Up to 20 reports / month\n"
        "- Up to 400k characters / month\n"
        "- Executive summaries + key insights"
    )
    if st.button("Choose Basic", key="choose_basic"):
        if not st.session_state["billing_email"]:
            st.error("Enter and save your billing email in Step 1 first.")
        else:
            start_checkout(st.session_state["billing_email"], "basic")

with col_pro:
    st.markdown("#### Pro\n$19.99 / month")
    st.write(
        "- Up to 75 reports / month\n"
        "- Up to 1.5M characters / month\n"
        "- Action items, risks, and opportunity insights"
    )
    if st.button("Choose Pro", key="choose_pro"):
        if not st.session_state["billing_email"]:
            st.error("Enter and save your billing email in Step 1 first.")
        else:
            start_checkout(st.session_state["billing_email"], "pro")

with col_ent:
    st.markdown("#### Enterprise\n$39.99 / month")
    st.write(
        "- Up to 250 reports / month\n"
        "- Up to 5M characters / month\n"
        "- Team accounts, shared templates, & premium support"
    )
    if st.button("Choose Enterprise", key="choose_ent"):
        if not st.session_state["billing_email"]:
            st.error("Enter and save your billing email in Step 1 first.")
        else:
            start_checkout(st.session_state["billing_email"], "enterprise")

st.markdown("---")
st.caption(
    "After you subscribe, return to the **Upload Data** tab to start generating "
    "client-ready summaries from your reports."
)
