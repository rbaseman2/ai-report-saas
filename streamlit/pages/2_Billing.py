# streamlit/pages/2_Billing.py

import os
import requests
import streamlit as st

# -------------------------------------------------------------------
# Streamlit config MUST be the first st.* call
# -------------------------------------------------------------------
st.set_page_config(page_title="Billing & Plans – AI Report", page_icon="💳")

# -------------------------------------------------------------------
# Backend URL configuration (env var only, no st.secrets)
# -------------------------------------------------------------------
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",  # fallback
).rstrip("/")


# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

def call_backend(endpoint: str, payload: dict, timeout: int = 15):
    """Small helper to POST JSON to the backend and return (ok, data_or_error_str)."""
    url = f"{BACKEND_URL}{endpoint}"

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.RequestException as e:
        return False, f"Could not reach backend: {e}"

    if not resp.ok:
        # Try to extract a useful error message
        try:
            data = resp.json()
            detail = data.get("detail") or data
        except Exception:
            detail = resp.text

        return False, f"Backend returned {resp.status_code}: {detail}"

    try:
        return True, resp.json()
    except Exception:
        return False, "Backend returned invalid JSON."


def get_query_param(name: str, default=None):
    """Safe access to st.query_params (new Streamlit API)."""
    params = st.query_params
    return params.get(name, default)


# -------------------------------------------------------------------
# Page content
# -------------------------------------------------------------------

st.title("Billing & Plans")
st.write(
    "Use this page to manage your subscription and upgrade your document summary limits."
)

# --- Handle query params from Stripe redirect --------------------------------
status = get_query_param("status")
session_id = get_query_param("session_id")

if status == "success" and session_id:
    st.success(
        "Checkout complete! To activate your new plan, make sure the same email you "
        "used at checkout is saved below, then click **Save email & check plan**."
    )
elif status == "cancel":
    st.info("Checkout was cancelled. You can choose a plan again below.")

# -------------------------------------------------------------------
# Step 1 – Add your email
# -------------------------------------------------------------------

st.subheader("Step 1 – Add your email")

st.write(
    "We use this email to link your subscription, upload limits, and summaries. "
    "Use the same email address you'll use at checkout."
)

if "saved_email" not in st.session_state:
    st.session_state.saved_email = ""

if "current_plan" not in st.session_state:
    st.session_state.current_plan = "free"

email = st.text_input(
    "Email address",
    value=st.session_state.saved_email,
    placeholder="you@example.com",
)


def refresh_subscription(email_value: str):
    """Call backend /subscription-status and update session state."""
    ok, data = call_backend("/subscription-status", {"email": email_value})

    if not ok:
        st.error(data)
        st.session_state.current_plan = "free"
        return

    plan = data.get("plan", "free")
    st.session_state.current_plan = plan
    st.session_state.saved_email = email_value

    if plan == "free":
        st.info(
            "Status: **Free plan**. We haven't detected an active subscription yet. "
            "You can upgrade in Step 2 below."
        )
    elif plan in ("basic", "pro", "enterprise"):
        plan_name = plan.capitalize()
        st.success(f"Status: **{plan_name} plan** is active for `{email_value}`.")
    else:
        st.warning(
            f"Status: **Unknown**. We found a subscription for `{email_value}`, "
            "but couldn't map it to one of the known plans."
        )


if st.button("Save email & check plan", type="primary"):
    if not email:
        st.error("Please enter an email address first.")
    else:
        refresh_subscription(email)

# Show current status if we already have it
if st.session_state.current_plan == "free" and not (status == "success" and session_id):
    st.caption(
        "Status: **Free plan**. We haven't detected an active subscription yet. "
        "You can upgrade in Step 2 below."
    )

# -------------------------------------------------------------------
# Step 2 – Choose a plan
# -------------------------------------------------------------------

st.subheader("Step 2 – Choose a plan")

st.write("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")


def start_checkout(plan: str):
    """Trigger Stripe Checkout for the given plan."""
    if not email:
        st.error("Please enter and save your email in Step 1 before choosing a plan.")
        return

    with st.spinner("Redirecting to Stripe Checkout…"):
        ok, data = call_backend(
            "/create-checkout-session",
            {"plan": plan, "email": email},
            timeout=25,
        )

    if not ok:
        st.error(data)
        return

    checkout_url = data.get("checkout_url")
    if not checkout_url:
        st.error("Backend did not return a checkout URL.")
        return

    st.success("Opening Stripe Checkout…")
    # Meta refresh redirect
    st.markdown(
        f"""
        <meta http-equiv="refresh" content="0; url={checkout_url}">
        """,
        unsafe_allow_html=True,
    )


col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Basic")
    st.markdown("**$9.99 / month**")
    st.markdown(
        "- Upload up to **5 documents** per month\n"
        "- Clear AI-generated summaries for clients and stakeholders\n"
        "- Copy-paste summaries into emails, reports, and slide decks"
    )
    if st.button("Choose Basic", key="choose_basic"):
        start_checkout("basic")

with col2:
    st.markdown("### Pro")
    st.markdown("**$19.99 / month**")
    st.markdown(
        "- Upload up to **30 documents** per month\n"
        "- Deeper, more structured summaries (key points, risks, and action items)\n"
        "- Priority email support"
    )
    if st.button("Choose Pro", key="choose_pro"):
        start_checkout("pro")

with col3:
    st.markdown("### Enterprise")
    st.markdown("**$39.99 / month**")
    st.markdown(
        "- **Unlimited uploads** for your team\n"
        "- Team accounts and shared templates\n"
        "- Premium support & integration help"
    )
    if st.button("Choose Enterprise", key="choose_enterprise"):
        start_checkout("enterprise")

# -------------------------------------------------------------------
# Step 3 – Start using your plan
# -------------------------------------------------------------------

st.subheader("Step 3 – Start using your plan")

st.markdown(
    "1. Go to the **Upload Data** page (link in the sidebar on the left).\n"
    "2. Enter the **same email** you used here.\n"
    "3. Upload a report or paste your content.\n"
    "4. Click **Generate Business Summary** to create a client-ready summary."
)

st.markdown("[Open Upload Data →](/Upload_Data)")
