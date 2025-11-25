# streamlit/pages/2_Billing.py

import os
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# Backend URL where FastAPI (webhook.py) is deployed
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",  # <-- adjust if needed
).rstrip("/")

REQUEST_TIMEOUT = 20  # seconds


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------
def fetch_subscription(email: str):
    """Call the backend /subscription endpoint for this email."""
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription",
            params={"email": email},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        st.error(f"Error reaching backend while checking subscription: {exc}")
        return None

    if resp.status_code != 200:
        st.error(
            f"Backend returned {resp.status_code} while checking subscription."
        )
        return None

    try:
        data = resp.json()
    except ValueError:
        st.error("Could not parse subscription response from backend.")
        return None

    # Expected shape:
    # { "email": "...", "plan": "basic"|"pro"|"enterprise"|null, "status": "none"|"active"|... }
    return data


def start_checkout(plan: str, email: str):
    """Create a Stripe Checkout session for the selected plan."""
    if not email:
        st.error("Please enter your email in Step 1 before choosing a plan.")
        return

    payload = {"plan": plan, "email": email}

    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        st.error(f"Error reaching backend during checkout: {exc}")
        return

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        st.error(f"Checkout failed ({resp.status_code}): {detail}")
        return

    try:
        checkout_url = resp.json()["checkout_url"]
    except (ValueError, KeyError):
        st.error("Backend did not return a checkout URL.")
        return

    # Redirect browser to Stripe Checkout
    st.success("Redirecting to secure Stripe checkout…")
    st.markdown(
        f"<meta http-equiv='refresh' content='0; url={checkout_url}'/>",
        unsafe_allow_html=True,
    )


def format_plan_label(plan: str | None, status: str | None) -> str:
    """Human-readable label for the current plan + status."""
    if plan is None or status is None or status == "none":
        return "Free plan (no active subscription found)."
    if status in ("active", "trialing"):
        return f"Current plan: **{plan.capitalize()}** (status: {status})."
    return f"Found subscription for **{plan.capitalize()}**, but status is **{status}**."


# -----------------------------------------------------------------------------
# Page layout
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Billing & Plans – AI Report", page_icon="💳")

st.title("Billing & Plans")

st.caption(
    "Use this page to manage your subscription and upgrade your document summary limits."
)

# -----------------------------------------------------------------------------  
# Handle query params from Stripe redirect
# -----------------------------------------------------------------------------
query_params = st.query_params
status_param = query_params.get("status")
session_id = query_params.get("session_id")

if status_param == "success":
    st.success(
        "Checkout complete! To activate your new plan, make sure the same email "
        "you used at checkout is saved below."
    )
elif status_param == "cancelled":
    st.info(
        "Checkout was cancelled. You can choose a plan again below whenever you're ready."
    )

# -----------------------------------------------------------------------------  
# Step 1 – Email + subscription status
# -----------------------------------------------------------------------------
st.subheader("Step 1 – Add your email")

default_email = st.session_state.get("billing_email", "")
email = st.text_input(
    "Email address",
    value=default_email,
    placeholder="you@example.com",
    help="Use the same email address you used (or will use) at checkout.",
)

check_clicked = st.button("Save email & check plan", type="primary")

subscription_info = None

if check_clicked:
    if not email:
        st.error("Please enter an email address.")
    else:
        st.session_state["billing_email"] = email
        with st.spinner("Checking your subscription…"):
            subscription_info = fetch_subscription(email)
            if subscription_info is not None:
                st.session_state["subscription_info"] = subscription_info

# If we already have subscription info from a previous check, reuse it
if subscription_info is None:
    subscription_info = st.session_state.get("subscription_info")

# Show subscription status banner
st.write("")  # spacing
if subscription_info:
    current_plan = subscription_info.get("plan")
    current_status = subscription_info.get("status")
    st.info(format_plan_label(current_plan, current_status))
else:
    st.info(
        "Status: **Free plan**. We haven't detected an active subscription yet. "
        "You can upgrade in Step 2 below."
    )

# -----------------------------------------------------------------------------  
# Step 2 – Choose a plan
# -----------------------------------------------------------------------------
st.subheader("Step 2 – Choose a plan")

active_plan = None
active_status = None
if subscription_info:
    active_plan = subscription_info.get("plan")
    active_status = subscription_info.get("status")

def is_active(plan_name: str) -> bool:
    return (
        active_plan == plan_name
        and active_status in ("active", "trialing")
    )

col_basic, col_pro, col_enterprise = st.columns(3)

with col_basic:
    st.markdown("### Basic")
    st.markdown("**$9.99 / month**")
    st.markdown(
        """
- Upload up to **5 documents per month**
- Clear AI-generated summaries for clients and stakeholders
- Copy-paste summaries into emails, reports, and slide decks
"""
    )
    disabled = is_active("basic")
    label = "Current plan" if disabled else "Choose Basic"
    if st.button(label, key="choose_basic", disabled=disabled):
        start_checkout("basic", email)

with col_pro:
    st.markdown("### Pro")
    st.markdown("**$19.99 / month**")
    st.markdown(
        """
- Upload up to **30 documents per month**
- Deeper, more structured summaries (key points, risks, and action items)
- Priority email support
"""
    )
    disabled = is_active("pro")
    label = "Current plan" if disabled else "Choose Pro"
    if st.button(label, key="choose_pro", disabled=disabled):
        start_checkout("pro", email)

with col_enterprise:
    st.markdown("### Enterprise")
    st.markdown("**$39.99 / month**")
    st.markdown(
        """
- **Unlimited uploads** for your team
- Team accounts and shared templates
- Premium support & integration help
"""
    )
    disabled = is_active("enterprise")
    label = "Current plan" if disabled else "Choose Enterprise"
    if st.button(label, key="choose_enterprise", disabled=disabled):
        start_checkout("enterprise", email)

# -----------------------------------------------------------------------------  
# Step 3 – Using your plan
# -----------------------------------------------------------------------------
st.subheader("Step 3 – Start using your plan")

st.markdown(
    """
1. Go to the **Upload Data** page (link in the sidebar on the left).  
2. Enter the **same email** you used here.  
3. Upload a report or paste your content.  
4. Click **Generate Business Summary** to create a client-ready summary.
"""
)

st.link_button("Open Upload Data →", "/Upload_Data")
