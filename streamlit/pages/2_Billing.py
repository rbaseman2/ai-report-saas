# 2_Billing.py  – clean version

import os
import textwrap
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# Backend FastAPI URL (set this in Render environment if you like)
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubx.onrender.com",  # <- change if your backend URL differs
)

# Public URL of this Billing page (used for Stripe success/cancel redirects)
BILLING_PAGE_URL = os.getenv(
    "BILLING_PAGE_URL",
    "https://ai-report-saas.onrender.com/Billing",  # <- change if your Streamlit URL differs
)

# Default limits for each plan (for display only – real limits enforced by backend)
DEFAULT_LIMITS = {
    "free": {"max_documents": 5, "max_chars": 200_000},
    "basic": {"max_documents": 20, "max_chars": 400_000},
    "pro": {"max_documents": 75, "max_chars": 1_500_000},
    "enterprise": {"max_documents": 250, "max_chars": 5_000_000},
}

# -----------------------------------------------------------------------------
# Streamlit page setup
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Billing & Subscription – AI Report", page_icon="💳")

st.title("Billing & Subscription")
st.write(
    "Choose a plan that matches how often you need to summarize reports. "
    "You can upgrade or downgrade at any time as your workload grows."
)

# -----------------------------------------------------------------------------
# Gently wake the backend so first real call is faster
# -----------------------------------------------------------------------------
try:
    requests.get(f"{BACKEND_URL}/health", timeout=3)
except Exception:
    # It's okay if this fails; the real calls below will still try again.
    pass

# -----------------------------------------------------------------------------
# Handle Stripe redirect query params (?status=success|cancel)
# -----------------------------------------------------------------------------
qp = st.query_params  # QueryParamsProxy (dict-like)

status_param = qp.get("status")
if status_param == "success":
    st.success(
        "Checkout complete! If this is a new subscription, your plan "
        "should update in a few seconds."
    )
elif status_param == "cancel":
    st.info("Checkout was cancelled. You can start again whenever you’re ready.")

# Clear the status param so the message doesn’t reappear on refresh
if status_param is not None:
    try:
        del st.query_params["status"]
    except KeyError:
        pass

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def get_plan_label(plan: str) -> str:
    plan = (plan or "free").lower()
    if plan == "basic":
        return "Basic"
    if plan == "pro":
        return "Pro"
    if plan == "enterprise":
        return "Enterprise"
    return "Free"


def get_limits_for_plan(plan: str) -> dict:
    plan = (plan or "free").lower()
    return DEFAULT_LIMITS.get(plan, DEFAULT_LIMITS["free"])


def check_subscription(email: str) -> tuple[str, dict]:
    """
    Call backend /subscription-status. Returns (plan, limits_dict).
    404 -> ("free", default_limits).
    Any error -> ("free", default_limits) and shows an error in the UI.
    """
    email = email.strip()
    if not email:
        st.warning("Please enter your billing email before checking your plan.")
        return "free", DEFAULT_LIMITS["free"]

    with st.spinner("Checking your subscription…"):
        try:
            resp = requests.get(
                f"{BACKEND_URL}/subscription-status",
                params={"email": email},
                timeout=20,
            )

            if resp.status_code == 404:
                # No active subscription – treat as Free plan
                return "free", DEFAULT_LIMITS["free"]

            resp.raise_for_status()
            data = resp.json()

            plan = (data.get("plan") or "free").lower()
            limits = {
                "max_documents": data.get(
                    "max_documents", DEFAULT_LIMITS.get(plan, DEFAULT_LIMITS["free"])["max_documents"]
                ),
                "max_chars": data.get(
                    "max_chars", DEFAULT_LIMITS.get(plan, DEFAULT_LIMITS["free"])["max_chars"]
                ),
            }
            return plan, limits

        except Exception as e:
            st.error(f"Error while checking subscription: {e}")
            return "free", DEFAULT_LIMITS["free"]


def start_checkout(plan_slug: str):
    """
    Start Stripe Checkout for the given plan ("basic", "pro", "enterprise").
    """
    email = st.session_state.get("billing_email", "").strip()
    if not email:
        st.warning("Enter your billing email in the box above before choosing a plan.")
        st.stop()

    success_url = f"{BILLING_PAGE_URL}?status=success"
    cancel_url = f"{BILLING_PAGE_URL}?status=cancel"

    with st.spinner("Creating checkout session…"):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/create-checkout-session",
                json={
                    "plan": plan_slug,  # backend decides which Stripe price to use
                    "email": email,
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                },
                timeout=60,  # allow time for Render backend to wake up
            )
            resp.raise_for_status()
            data = resp.json()
            checkout_url = data.get("checkout_url")

            if not checkout_url:
                st.error("Backend did not return a checkout URL.")
                return

            # Redirect user to Stripe Checkout
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={checkout_url}">',
                unsafe_allow_html=True,
            )

        except requests.exceptions.Timeout:
            st.error(
                "The server took too long to respond (it may be waking up). "
                "Please wait a few seconds and click the plan button again."
            )
        except Exception as e:
            st.error(f"Network error starting checkout: {e}")


# -----------------------------------------------------------------------------
# Step 1 – Billing email + current plan
# -----------------------------------------------------------------------------
st.subheader("Step 1 – Your billing email")

if "billing_email" not in st.session_state:
    st.session_state["billing_email"] = ""

billing_email = st.text_input(
    "Use the same email address you complete checkout with:",
    value=st.session_state["billing_email"],
    placeholder="you@company.com",
)

col_check, _ = st.columns([1, 3])
with col_check:
    if st.button("Save email & check plan", type="primary"):
        st.session_state["billing_email"] = billing_email.strip()
        plan, limits = check_subscription(st.session_state["billing_email"])
        st.session_state["current_plan"] = plan
        st.session_state["current_limits"] = limits

# Determine what to display right now
current_plan = st.session_state.get("current_plan", "free")
current_limits = st.session_state.get(
    "current_limits", get_limits_for_plan(current_plan)
)

st.markdown("### Current plan")

st.info(
    textwrap.dedent(
        f"""
        **Status:** {get_plan_label(current_plan)} plan  
        You can upload up to **{current_limits['max_documents']} reports** and up to 
        **{current_limits['max_chars']:,} characters** per month on this plan.
        """
    )
)

st.caption(
    "These limits are enforced by the backend. If you upgrade or downgrade, "
    "click **Save email & check plan** again to refresh your status."
)

st.divider()

# -----------------------------------------------------------------------------
# Step 2 – Choose a plan
# -----------------------------------------------------------------------------
st.subheader("Step 2 – Choose a plan")

st.write("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

col_basic, col_pro, col_ent = st.columns(3)

with col_basic:
    st.markdown("#### Basic\n$9.99 / month")
    st.write(
        "- Up to 20 reports / month\n"
        "- Up to 400k characters / month\n"
        "- Executive summaries + key insights"
    )
    if st.button("Choose Basic"):
        start_checkout("basic")

with col_pro:
    st.markdown("#### Pro\n$19.99 / month")
    st.write(
        "- Up to 75 reports / month\n"
        "- Up to 1.5M characters / month\n"
        "- Action items, risks, and opportunity insights"
    )
    if st.button("Choose Pro"):
        start_checkout("pro")

with col_ent:
    st.markdown("#### Enterprise\n$49.99 / month")
    st.write(
        "- Up to 250 reports / month\n"
        "- Up to 5M characters / month\n"
        "- Priority processing & extended history"
    )
    if st.button("Choose Enterprise"):
        start_checkout("enterprise")

st.divider()

st.markdown(
    "After you subscribe, go to the **Upload Data** tab to start generating "
    "client-ready summaries from your reports."
)
