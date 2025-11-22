import os
import requests
import streamlit as st

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------

BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",
).rstrip("/")

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def fetch_subscription_status(email: str) -> dict:
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    # Fallback
    return {"plan": "free", "status": "none"}


def start_checkout(plan: str, email: str):
    if not email:
        st.error("Please enter your email above before choosing a plan.")
        return

    payload = {"plan": plan, "email": email}
    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json=payload,          # IMPORTANT: send JSON, not form data
            timeout=30,
        )
    except Exception as e:
        st.error(f"Unable to reach billing backend: {e}")
        return

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        st.error(f"Checkout failed ({resp.status_code}): {detail}")
        return

    data = resp.json()
    checkout_url = data.get("checkout_url")
    if not checkout_url:
        st.error("Backend did not return a checkout URL.")
        return

    st.success("Checkout session created. Click the button below to open Stripe Checkout.")
    st.markdown(f"[Open Stripe Checkout]({checkout_url})", unsafe_allow_html=True)


# --------------------------------------------------------------------
# Page layout
# --------------------------------------------------------------------

st.set_page_config(page_title="Billing & Plans – AI Report", page_icon="💳")

st.title("Billing & Plans")

st.caption(
    "Pick a plan that fits the way you work. Use the same email address on this page "
    "and on the **Upload Data** page so your subscription can be linked."
)

# Email input
if "billing_email" not in st.session_state:
    st.session_state["billing_email"] = ""

email = st.text_input(
    "Email address",
    value=st.session_state["billing_email"],
    placeholder="you@example.com",
)

col_save, _ = st.columns([1, 4])
with col_save:
    if st.button("Save email", type="primary"):
        st.session_state["billing_email"] = email.strip()
        st.success("Email saved. You can now choose a plan.")

email = st.session_state["billing_email"].strip()

# Show current subscription status if we have an email
status_container = st.empty()
if email:
    info = fetch_subscription_status(email)
    current_plan = info.get("plan", "free")
    sub_status = info.get("status", "none")

    nice_plan = current_plan.capitalize() if current_plan != "free" else "Free"
    if sub_status == "active":
        status_container.success(f"Current plan for **{email}**: **{nice_plan}** (active)")
    elif sub_status == "pending":
        status_container.info(
            f"Upgrade for **{email}** is pending Stripe confirmation. "
            f"If you just completed checkout, refresh this page in a few seconds."
        )
    elif current_plan != "free":
        status_container.warning(
            f"Plan for **{email}**: **{nice_plan}** (status: {sub_status}). "
            f"If this looks wrong, contact support."
        )
    else:
        status_container.info(
            f"Current plan for **{email}**: **Free**. "
            f"Upgrade below to unlock higher limits and richer summaries."
        )
else:
    status_container.info("Enter and save your email to see your current plan.")

st.markdown("---")

# --------------------------------------------------------------------
# Plans section
# --------------------------------------------------------------------

st.subheader("Step 2 – Choose a plan")

plans_col1, plans_col2, plans_col3 = st.columns(3)

with plans_col1:
    st.markdown("### Basic")
    st.markdown("**$9.99 / month**")
    st.markdown(
        """
- Upload up to **5 documents per month**
- Clear AI-generated summaries for clients and stakeholders
- Copy-paste summaries into emails, reports, and slide decks
        """
    )
    if st.button("Choose Basic", key="choose_basic"):
        start_checkout("basic", email)

with plans_col2:
    st.markdown("### Pro")
    st.markdown("**$19.99 / month**")
    st.markdown(
        """
- Upload up to **30 documents per month**
- Deeper, more structured summaries (key points, risks, and action items)
- Priority email support
        """
    )
    if st.button("Choose Pro", key="choose_pro"):
        start_checkout("pro", email)

with plans_col3:
    st.markdown("### Enterprise")
    st.markdown("**$39.99 / month**")
    st.markdown(
        """
- **Unlimited uploads** for your team
- Team accounts and shared templates
- Premium support and integration help
        """
    )
    if st.button("Choose Enterprise", key="choose_enterprise"):
        start_checkout("enterprise", email)

st.markdown("---")

st.subheader("Step 3 – Start using your plan")

st.markdown(
    """
1. Go to the **Upload Data** page (link in the sidebar or below).  
2. Enter the **same email** you used here.  
3. Upload a report or paste your content.  
4. Click **Generate Business Summary** to create a client-ready summary.
"""
)

st.markdown("[Open Upload Data →](/Upload_Data)")
