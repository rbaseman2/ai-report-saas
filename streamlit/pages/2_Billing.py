import os
import requests
import streamlit as st

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL") or st.secrets.get("BACKEND_URL", "")
BACKEND_URL = BACKEND_URL.rstrip("/")

if not BACKEND_URL:
    st.set_page_config(page_title="Billing & Subscription", page_icon="💳")
    st.error("BACKEND_URL is not configured. Please set it in Render env vars.")
    st.stop()

st.set_page_config(page_title="Billing & Subscription", page_icon="💳")

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def fetch_subscription_status(email: str):
    if not email:
        return None

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=10,
        )
    except Exception as e:
        st.error(f"Error contacting billing backend: {e}")
        return None

    if not resp.ok:
        st.error(
            f"Unexpected response from billing backend "
            f"({resp.status_code}: {resp.text})"
        )
        return None

    return resp.json()


def start_checkout(plan_key: str, email: str):
    if not email:
        st.warning("Please enter your billing email first.")
        return

    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan_key, "email": email},
            timeout=15,
        )
    except Exception as e:
        st.error(f"Checkout error: could not reach billing backend: {e}")
        return

    if not resp.ok:
        st.error(f"Checkout error: {resp.status_code} {resp.text}")
        return

    try:
        data = resp.json()
    except ValueError:
        st.error("Checkout error: backend returned non-JSON response.")
        return

    checkout_url = data.get("checkout_url") or data.get("url")
    if not checkout_url:
        st.error("Checkout error: backend did not return a checkout URL.")
        st.write("Raw response:", data)
        return

    st.success("Redirecting you to Stripe Checkout…")
    # Redirect in-place
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={checkout_url}">',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------
# UI
# --------------------------------------------------------------------
st.title("Billing & Subscription")

# --- NEW: use st.query_params instead of experimental_get_query_params ---
params = st.query_params
status = params.get("status", None)

if isinstance(status, list):
    status = status[0]

if status == "success":
    st.success("Payment successful! Your subscription is now active.")
elif status == "cancelled":
    st.info("Checkout was cancelled. You can select a plan again at any time.")

st.markdown("### Step 1 – Enter your email")

billing_email = st.text_input(
    "Billing email (used to associate your subscription)",
    key="billing_email",
    placeholder="you@example.com",
)

col_btn, col_status = st.columns([1, 3])

with col_btn:
    check_clicked = st.button("Save email & check\ncurrent plan")

current_status = None
if check_clicked and billing_email:
    current_status = fetch_subscription_status(billing_email)

with col_status:
    if current_status is not None:
        if current_status.get("has_active_subscription"):
            plan_name = current_status.get("plan") or "Active subscription"
            st.success(
                f"Active subscription found for this email. "
                f"Plan: **{plan_name}**."
            )
        else:
            st.info("No active subscription found for this email.")

st.write(
    "Status:",
    "active"
    if (current_status or {}).get("has_active_subscription")
    else "none",
)

st.markdown("---")
st.markdown("### Step 2 – Compare plans & upgrade")
st.write(
    "Pick the plan that best fits your workload. "
    "You can upgrade later as your needs grow."
)

col_basic, col_pro, col_ent = st.columns(3)

with col_basic:
    st.subheader("Basic")
    st.caption("$9.99 / month")
    st.markdown(
        """
- Up to 20 reports / month  
- Up to 400k characters / month  
- Executive summaries + key insights
        """
    )
    if st.button("Choose Basic"):
        start_checkout("basic", billing_email)

with col_pro:
    st.subheader("Pro")
    st.caption("$19.99 / month")
    st.markdown(
        """
- Up to 75 reports / month  
- Up to 1.5M characters / month  
- Action items, risks, and opportunity insights
        """
    )
    if st.button("Choose Pro"):
        start_checkout("pro", billing_email)

with col_ent:
    st.subheader("Enterprise")
    st.caption("$39.99 / month")
    st.markdown(
        """
- Up to 250 reports / month  
- Up to 5M characters / month  
- Team accounts, shared templates, & premium support
        """
    )
    if st.button("Choose Enterprise"):
        start_checkout("enterprise", billing_email)

st.markdown("---")
st.write(
    "After you subscribe, return to the **Upload Data** tab to start "
    "generating client-ready summaries from your reports."
)
