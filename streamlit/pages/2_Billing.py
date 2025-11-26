import os
import requests
import streamlit as st
from urllib.parse import urlencode

st.set_page_config(page_title="Billing & Plans – AI Report")

# ---------------------------------------------------------
# Config: read from environment (NOT st.secrets)
# ---------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

# Fallback so the app still works even if BACKEND_URL isn't set
if not BACKEND_URL:
    # You can remove this fallback once BACKEND_URL is set in Render
    BACKEND_URL = "https://ai-report-backend-ubrx.onrender.com"
    st.warning(
        "BACKEND_URL was not set in the environment. "
        "Using default backend URL for now."
    )

st.title("Billing & Plans")
st.caption(
    "Use this page to manage your subscription and upgrade your document summary limits."
)

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def subscription_status(email: str):
    """Ask the backend what plan this email is on."""
    try:
        resp = requests.post(
            f"{BACKEND_URL}/subscription-status",
            json={"email": email},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def create_checkout_session(plan: str, email: str):
    """Start a Stripe Checkout session via the backend."""
    params = {
        "status": "success",
    }
    success_url = f"{FRONTEND_URL}/Billing?{urlencode(params)}"
    cancel_url = f"{FRONTEND_URL}/Billing?status=cancel"

    payload = {
        "plan": plan,
        "email": email,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }

    resp = requests.post(
        f"{BACKEND_URL}/create-checkout-session",
        json=payload,
        timeout=30,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code} {resp.text}")

    data = resp.json()
    return data.get("checkout_url")


# ---------------------------------------------------------
# Step 0 – handle return from Stripe
# ---------------------------------------------------------
query_params = st.query_params()
status_param = query_params.get("status", [None])[0]

if status_param == "success":
    st.success(
        "Checkout complete! To activate your new plan, "
        "make sure the same email you used at checkout is saved below."
    )
elif status_param == "cancel":
    st.info("Checkout was canceled. You can start again by choosing a plan below.")

st.markdown("---")

# ---------------------------------------------------------
# Step 1 – Add your email
# ---------------------------------------------------------
st.subheader("Step 1 – Add your email")

default_email = st.session_state.get("user_email", "")
email = st.text_input(
    "Email address",
    value=default_email,
    placeholder="you@example.com",
)

if email and email != default_email:
    st.session_state["user_email"] = email

check_button = st.button("Save email & check plan")

plan_status_placeholder = st.empty()
plan_info = None

if email and check_button:
    with st.spinner("Checking your subscription…"):
        plan_info = subscription_status(email)

    if not plan_info:
        plan_status_placeholder.warning(
            "We couldn't verify an active subscription for this email yet. "
            "You're currently on the **Free plan**."
        )
    else:
        plan = plan_info.get("plan", "free")
        if plan == "basic":
            plan_status_placeholder.success(
                "Status: **Basic plan** – up to 5 documents per month with full summaries."
            )
        elif plan == "pro":
            plan_status_placeholder.success(
                "Status: **Pro plan** – up to 30 documents per month with richer analysis."
            )
        elif plan == "enterprise":
            plan_status_placeholder.success(
                "Status: **Enterprise plan** – unlimited uploads for your team."
            )
        else:
            plan_status_placeholder.info(f"Status: **{plan.capitalize()}** plan.")

elif not email:
    plan_status_placeholder.info("Enter your email above, then click **Save email & check plan**.")
else:
    # No button click yet; show last known status if we have it
    plan_status_placeholder.info(
        "Status: Free plan. We haven't detected an active subscription yet. "
        "You can upgrade in Step 2 below."
    )

st.markdown("---")

# ---------------------------------------------------------
# Step 2 – Choose a plan
# ---------------------------------------------------------
st.subheader("Step 2 – Choose a plan")

if not email:
    st.warning("Enter and save your email in Step 1 before choosing a plan.")

col_basic, col_pro, col_ent = st.columns(3)

with col_basic:
    st.markdown("### Basic")
    st.markdown("**$9.99 / month**")
    st.markdown("""
- Upload up to **5 documents per month**
- Clear AI-generated summaries for clients and stakeholders
- Copy-paste summaries into emails, reports, and slide decks
    """)
    if st.button("Choose Basic", key="choose_basic", disabled=not email):
        try:
            with st.spinner("Creating checkout session…"):
                url = create_checkout_session("basic", email)
            st.success("Redirecting to checkout…")
            st.experimental_set_query_params()  # clear status
            st.write(f"[Click here if you are not redirected]({url})")
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={url}">',
                unsafe_allow_html=True,
            )
        except Exception as e:
            st.error(f"Checkout failed: {e}")

with col_pro:
    st.markdown("### Pro")
    st.markdown("**$19.99 / month**")
    st.markdown("""
- Upload up to **30 documents per month**
- Deeper, more structured summaries (key points, risks, and action items)
- Priority email support
    """)
    if st.button("Choose Pro", key="choose_pro", disabled=not email):
        try:
            with st.spinner("Creating checkout session…"):
                url = create_checkout_session("pro", email)
            st.success("Redirecting to checkout…")
            st.experimental_set_query_params()
            st.write(f"[Click here if you are not redirected]({url})")
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={url}">',
                unsafe_allow_html=True,
            )
        except Exception as e:
            st.error(f"Checkout failed: {e}")

with col_ent:
    st.markdown("### Enterprise")
    st.markdown("**$39.99 / month**")
    st.markdown("""
- **Unlimited uploads** for your team
- Team accounts and shared templates
- Premium support & integration help
    """)
    if st.button("Choose Enterprise", key="choose_enterprise", disabled=not email):
        try:
            with st.spinner("Creating checkout session…"):
                url = create_checkout_session("enterprise", email)
            st.success("Redirecting to checkout…")
            st.experimental_set_query_params()
            st.write(f"[Click here if you are not redirected]({url})")
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={url}">',
                unsafe_allow_html=True,
            )
        except Exception as e:
            st.error(f"Checkout failed: {e}")

st.markdown("---")
st.subheader("Step 3 – Start using your plan")
st.markdown(
    """
1. Go to the **Upload Data** page (link in the sidebar on the left).  
2. Enter the **same email** you used here.  
3. Upload a report or paste your content.  
4. Click **Generate Business Summary** to create a client-ready summary.
"""
)
