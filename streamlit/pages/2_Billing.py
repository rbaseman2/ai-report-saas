import os
import requests
import streamlit as st

# -------------------------------
# CONFIG
# -------------------------------
st.set_page_config(page_title="Billing & Subscription", page_icon="💳")

BACKEND_URL = os.getenv("BACKEND_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

if not BACKEND_URL:
    st.error("BACKEND_URL is not set. Configure it in your Render environment variables.")
    st.stop()

# Default limits (used when no subscription or backend error)
DEFAULT_PLAN_INFO = {
    "plan": "free",
    "max_documents": 5,
    "max_chars": 200_000,
}

PLAN_LABELS = {
    "free": "Free",
    "basic": "Basic",
    "pro": "Pro",
    "enterprise": "Enterprise",
}

# -------------------------------
# HELPER FUNCTIONS
# -------------------------------
def fetch_subscription_status(email: str) -> dict:
    """
    Call backend /subscription-status to see current plan + limits.
    """
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=20,
        )
    except Exception as e:
        st.error(f"Error while contacting backend: {e}")
        return DEFAULT_PLAN_INFO

    if resp.status_code == 404:
        # No subscription found → free plan
        return DEFAULT_PLAN_INFO

    if not resp.ok:
        st.error(f"Backend returned {resp.status_code} while checking subscription: {resp.text}")
        return DEFAULT_PLAN_INFO

    data = resp.json()
    # Ensure keys exist
    return {
        "plan": data.get("plan", "free"),
        "max_documents": data.get("max_documents", DEFAULT_PLAN_INFO["max_documents"]),
        "max_chars": data.get("max_chars", DEFAULT_PLAN_INFO["max_chars"]),
    }


def start_checkout(tier: str):
    """
    Ask backend to create a Stripe Checkout session for the selected tier.
    """
    email = st.session_state.get("billing_email", "").strip()
    if not email:
        st.error("Please enter your email above before choosing a plan.")
        return

    payload = {"email": email, "tier": tier}

    with st.spinner("Creating secure checkout session…"):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/create-checkout-session",
                json=payload,
                timeout=25,
            )
        except Exception as e:
            st.error(f"Network error while starting checkout: {e}")
            return

    if not resp.ok:
        st.error(f"Backend returned {resp.status_code} while starting checkout: {resp.text}")
        return

    data = resp.json()
    checkout_url = data.get("checkout_url")

    if not checkout_url:
        st.error("Backend did not return a checkout URL.")
        return

    st.success("Checkout session created. Opening Stripe checkout…")

    # Auto-redirect to Stripe checkout (plus show a fallback link)
    st.markdown(
        f"""
        <meta http-equiv="refresh" content="0; url={checkout_url}">
        If you are not redirected automatically, click
        [here to open checkout]({checkout_url}).
        """,
        unsafe_allow_html=True,
    )


# -------------------------------
# PAGE CONTENT
# -------------------------------
st.title("Billing & Subscription")

# Handle query params from Stripe redirect (?status=success|cancelled)
q = st.query_params
status_param = q.get("status")

if status_param == "success":
    st.success(
        "Checkout complete! To activate your plan, make sure you use the same email "
        "here and on the Upload Data page."
    )
elif status_param == "cancelled":
    st.info("Checkout was cancelled. You can restart it any time below.")

st.write(
    "Choose a plan that matches how often you need to summarize reports. "
    "You can upgrade at any time as your workload grows."
)

# -------------------------------
# STEP 1 – EMAIL + CURRENT PLAN
# -------------------------------
st.subheader("Step 1 – Your billing email")

email_default = st.session_state.get("billing_email", "")
email = st.text_input(
    "Billing email",
    value=email_default,
    placeholder="you@example.com",
    help="Use the same email you entered at checkout.",
)

if email:
    st.session_state["billing_email"] = email

if st.button("Save email & check current plan", type="primary"):
    if not email:
        st.error("Please enter your email.")
    else:
        plan_info = fetch_subscription_status(email)
        st.session_state["plan_info"] = plan_info

# Show current plan (from session or default)
plan_info = st.session_state.get("plan_info", DEFAULT_PLAN_INFO)
plan_key = plan_info.get("plan", "free")
plan_label = PLAN_LABELS.get(plan_key, "Free")

st.subheader("Current plan")
st.write(f"**Status:** {plan_label} plan")

st.write(
    f"You can upload up to **{plan_info['max_documents']}** reports per month, "
    f"with a total of about **{plan_info['max_chars']:,}** characters per month."
)

st.info("Your plan controls how many reports you can upload and the maximum "
        "length we can summarize each month.")

# -------------------------------
# STEP 2 – CHOOSE A PLAN
# -------------------------------
st.subheader("Step 2 – Compare plans & upgrade")

st.write("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Basic\n$9.99 / month")
    st.write("- Up to 20 reports / month")
    st.write("- Up to 400k characters / month")
    st.write("- Executive summaries + key insights")
    if st.button("Choose Basic", key="choose_basic"):
        start_checkout("basic")

with col2:
    st.markdown("### Pro\n$19.99 / month")
    st.write("- Up to 75 reports / month")
    st.write("- Up to 1.5M characters / month")
    st.write("- Action items, risks, and opportunity insights")
    if st.button("Choose Pro", key="choose_pro"):
        start_checkout("pro")

with col3:
    st.markdown("### Enterprise\n$49.99 / month")
    st.write("- Up to 250 reports / month")
    st.write("- Up to 5M characters / month")
    st.write("- Priority processing & extended history")
    if st.button("Choose Enterprise", key="choose_enterprise"):
        start_checkout("enterprise")

st.caption(
    "After you subscribe, come back to this page and click "
    "**Save email & check current plan** to refresh your subscription status."
)
