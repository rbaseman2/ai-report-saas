# pages/2_Billing.py

import os
import requests
import streamlit as st

# -------------------------------------------------------------------
# Setup
# -------------------------------------------------------------------

st.set_page_config(page_title="Billing & Subscription", page_icon="💳")

BACKEND_URL = st.secrets.get("BACKEND_URL", os.getenv("BACKEND_URL", "http://localhost:8000"))

st.title("Billing & Subscription")
st.write(
    "Choose a plan that matches how often you need to summarize reports. "
    "You can upgrade at any time as your workload grows."
)

# Read redirect params from Stripe
params = st.query_params
status = params.get("status")
session_id = params.get("session_id")

if status == "success" and session_id:
    st.success(
        "Checkout complete! Your payment was processed successfully. "
        "Enter your billing email below and click **Save email & check current plan** "
        "to refresh your subscription status."
    )
elif status == "cancelled":
    st.info("Looks like you cancelled checkout. You can try again anytime.")

st.write("---")

# -------------------------------------------------------------------
# Step 1 – Billing email & current plan
# -------------------------------------------------------------------

st.subheader("Step 1 – Your billing email")

billing_email = st.text_input(
    "Billing email",
    key="billing_email",
    help="Use the same email you used at checkout.",
)

if "current_plan_info" not in st.session_state:
    st.session_state["current_plan_info"] = None


def fetch_plan(email: str):
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=20,
        )
        if resp.status_code == 404:
            # Treat as free if backend explicitly returns 404
            st.session_state["current_plan_info"] = {
                "plan": "free",
                "max_documents": 5,
                "max_chars": 200_000,
            }
            return

        resp.raise_for_status()
        st.session_state["current_plan_info"] = resp.json()
    except Exception as e:
        st.error(f"Error while contacting backend: {e}")
        st.session_state["current_plan_info"] = None


if st.button("Save email & check current plan"):
    if not billing_email.strip():
        st.error("Please enter your billing email first.")
    else:
        fetch_plan(billing_email.strip())

plan_info = st.session_state.get("current_plan_info")

with st.container(border=True):
    st.subheader("Current plan")
    if plan_info is None:
        st.write("Status: **Unknown** – click the button above to check your plan.")
        st.write(
            "By default, we treat you as on the **Free** plan until we can contact the billing server."
        )
    else:
        plan_name = plan_info.get("plan", "free").capitalize()
        docs = plan_info.get("max_documents", 5)
        chars = plan_info.get("max_chars", 200_000)
        st.write(f"Status: **{plan_name}** plan")
        st.write(
            f"You can upload up to **{docs} reports per month**, with a total of about "
            f"**{chars:,} characters**."
        )

st.write("---")

# -------------------------------------------------------------------
# Step 2 – Compare plans & start checkout
# -------------------------------------------------------------------

st.subheader("Step 2 – Compare plans & upgrade")


def start_checkout(plan_slug: str):
    email = billing_email.strip()
    if not email:
        st.error("Please enter your billing email above before choosing a plan.")
        return

    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan_slug, "email": email},
            timeout=20,
        )
        resp.raise_for_status()
        checkout_url = resp.json()["checkout_url"]

        st.success(
            f"Redirecting you to Stripe Checkout for the **{plan_slug.capitalize()}** plan..."
        )
        # Open in a new tab
        st.markdown(
            f"""
            <script>
            window.open("{checkout_url}", "_blank");
            </script>
            """,
            unsafe_allow_html=True,
        )
    except Exception as e:
        st.error(f"Network error starting checkout: {e}")


col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Basic\n\n$9.99 / month")
    st.write("- Up to 20 reports / month")
    st.write("- Up to 400k characters / month")
    st.write("- Executive summaries + key insights")
    if st.button("Choose Basic"):
        start_checkout("basic")

with col2:
    st.markdown("### Pro\n\n$19.99 / month")
    st.write("- Up to 75 reports / month")
    st.write("- Up to 1.5M characters / month")
    st.write("- Action items, risks, and opportunity insights")
    if st.button("Choose Pro"):
        start_checkout("pro")

with col3:
    st.markdown("### Enterprise\n\n$49.99 / month")
    st.write("- Up to 250 reports / month")
    st.write("- Up to 5M characters / month")
    st.write("- Priority processing & extended history")
    if st.button("Choose Enterprise"):
        start_checkout("enterprise")

st.write("---")
st.info(
    "After you subscribe, return to the **Upload Data** tab with the same email to start "
    "generating client-ready summaries from your reports."
)
