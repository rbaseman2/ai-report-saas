import os
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Billing & Plans", page_icon="💳")

st.title("Billing & Plans")

# Where your backend (FastAPI) is hosted
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com"  # <-- your current backend URL
)

# Base URL of this Streamlit app
FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "https://ai-report-saas.onrender.com"  # <-- can override via env if needed
)

SUCCESS_URL = FRONTEND_URL + "/Billing?status=success"
CANCEL_URL = FRONTEND_URL + "/Billing?status=cancelled"

# Same plan IDs you configured in your backend / Stripe
PLANS = {
    "basic": {
        "name": "Basic",
        "price_id": os.getenv("PRICE_BASIC", ""),  # optional; backend can map instead
        "price_label": "$9.99 / month",
        "bullets": [
            "Upload up to 5 documents per month",
            "Clear AI-generated summaries for clients and stakeholders",
            "Copy-paste summaries into emails, reports, and slide decks",
        ],
    },
    "pro": {
        "name": "Pro",
        "price_id": os.getenv("PRICE_PRO", ""),
        "price_label": "$19.99 / month",
        "bullets": [
            "Upload up to 30 documents per month",
            "Deeper, more structured summaries (key points, risks, and action items)",
            "Priority email support",
        ],
    },
    "enterprise": {
        "name": "Enterprise",
        "price_id": os.getenv("PRICE_ENTERPRISE", ""),
        "price_label": "$39.99 / month",
        "bullets": [
            "Unlimited uploads for your team",
            "Team accounts and shared templates",
            "Premium support & integration help",
        ],
    },
}


# -----------------------------------------------------------------------------
# Helper to call backend
# -----------------------------------------------------------------------------
def start_checkout(plan_key: str, email: str) -> str | None:
    """
    Ask the backend to create a Stripe Checkout session and return the URL.
    """
    plan = PLANS[plan_key]

    # You can either send price_id here, or just send the plan_key and let
    # the backend map it to the right Stripe price. This example sends both.
    payload = {
        "plan": plan_key,
        "price_id": plan["price_id"] or None,
        "customer_email": email,
        "success_url": SUCCESS_URL,
        "cancel_url": CANCEL_URL,
    }

    try:
        resp = requests.post(f"{BACKEND_URL}/create-checkout-session", json=payload, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        st.error(f"Checkout failed: {e}")
        return None

    data = resp.json()
    checkout_url = data.get("checkout_url") or data.get("url")
    if not checkout_url:
        st.error("Checkout failed: backend did not return a checkout URL.")
        return None

    return checkout_url


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
st.write(
    "Use this page to manage your subscription and upgrade your document "
    "summary limits."
)

# Email
st.subheader("Your email")
email = st.text_input(
    "Email address",
    placeholder="you@example.com",
    help="We use this email to link your subscription, upload limits, and summaries.",
)

st.markdown("---")

# Show any status from query params (e.g. after Stripe redirect)
qp = st.experimental_get_query_params()
status = qp.get("status", [None])[0]

if status == "success":
    st.success("✅ Payment successful. Your subscription has been updated.")
elif status == "cancelled":
    st.info("Payment canceled. You can try again or choose a different plan.")


st.subheader("Plans")

cols = st.columns(3)

# ---- Basic Plan ----
with cols[0]:
    plan = PLANS["basic"]
    st.markdown(f"### {plan['name']}")
    st.caption(plan["price_label"])
    for bullet in plan["bullets"]:
        st.markdown(f"- {bullet}")

    if st.button("Choose Basic", key="choose_basic", use_container_width=True):
        if not email.strip():
            st.warning("Please enter your email before choosing a plan.")
        else:
            url = start_checkout("basic", email.strip())
            if url:
                st.experimental_set_query_params()  # clear params
                st.experimental_rerun()  # let Streamlit reload before redirect
                st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)

# ---- Pro Plan ----
with cols[1]:
    plan = PLANS["pro"]
    st.markdown(f"### {plan['name']}")
    st.caption(plan["price_label"])
    for bullet in plan["bullets"]:
        st.markdown(f"- {bullet}")

    if st.button("Choose Pro", key="choose_pro", use_container_width=True):
        if not email.strip():
            st.warning("Please enter your email before choosing a plan.")
        else:
            url = start_checkout("pro", email.strip())
            if url:
                st.experimental_set_query_params()
                st.experimental_rerun()
                st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)

# ---- Enterprise Plan ----
with cols[2]:
    plan = PLANS["enterprise"]
    st.markdown(f"### {plan['name']}")
    st.caption(plan["price_label"])
    for bullet in plan["bullets"]:
        st.markdown(f"- {bullet}")

    if st.button("Choose Enterprise", key="choose_enterprise", use_container_width=True):
        if not email.strip():
            st.warning("Please enter your email before choosing a plan.")
        else:
            url = start_checkout("enterprise", email.strip())
            if url:
                st.experimental_set_query_params()
                st.experimental_rerun()
                st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)

st.markdown("---")
st.caption(
    "After a successful checkout, your plan will be updated automatically and your "
    "upload limits will adjust on the **Upload Data** page."
)
