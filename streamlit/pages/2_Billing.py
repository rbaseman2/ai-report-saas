import os
import requests
import streamlit as st

st.set_page_config(
    page_title="Billing & Plans – AI Report",
    page_icon="💳",
    layout="wide",
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

PLAN_CONFIG = {
    "basic": {
        "name": "Basic",
        "price": "$9.99 / month",
        "description": [
            "Upload up to **5 documents per month**",
            "Clear AI-generated summaries for clients and stakeholders",
            "Copy-paste summaries into emails, reports, and slide decks",
        ],
    },
    "pro": {
        "name": "Pro",
        "price": "$19.99 / month",
        "description": [
            "Upload up to **30 documents per month**",
            "Deeper, more structured summaries (key points, risks, and action items)",
            "Priority email support",
        ],
    },
    "enterprise": {
        "name": "Enterprise",
        "price": "$39.99 / month",
        "description": [
            "**Unlimited uploads** for your team",
            "Team accounts and shared templates",
            "Premium support & integration help",
        ],
    },
}


def get_backend_url() -> str:
    return BACKEND_URL.rstrip("/")


def get_subscription(email: str) -> dict:
    if not email:
        return {"plan": "free"}

    try:
        resp = requests.get(
            f"{get_backend_url()}/subscription/status",
            params={"email": email},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            if "plan" not in data:
                data["plan"] = "free"
            return data
    except Exception:
        pass

    return {"plan": "free"}


def create_checkout_session(email: str, plan_id: str) -> str | None:
    """
    Ask the backend to create a Stripe Checkout session and return the URL.
    """
    try:
        resp = requests.post(
            f"{get_backend_url()}/create-checkout-session",
            json={"email": email, "price_id": plan_id},
            timeout=30,
        )
        if resp.ok:
            data = resp.json()
            return data.get("checkout_url")
        else:
            st.error(
                f"Checkout failed: {resp.status_code} {resp.reason} "
                f"for url: {resp.url}"
            )
    except Exception as e:
        st.error(f"Checkout failed: {e}")
    return None


# ---------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------

st.title("Billing & Plans")

st.caption(
    "Use this page to manage your subscription and upgrade your document limits."
)

# Query params (e.g. Stripe redirect with ?status=success)
qp = st.query_params
status_param = qp.get("status", [None])[0] if qp else None

if status_param == "success":
    st.success(
        "✅ Your payment was successful and your subscription is now active. "
        "You can go to the **Upload Data** page to start generating summaries."
    )
    st.markdown("[Go to Upload Data →](/Upload_Data)")
elif status_param == "cancel":
    st.info(
        "You cancelled checkout. You can choose a plan again below whenever you’re ready."
    )

st.divider()

# ----------------------------- STEP 1: EMAIL -------------------------

st.markdown("### Step 1 – Add your email")

default_email = st.session_state.get("user_email", "")
email = st.text_input(
    "Email address",
    value=default_email,
    placeholder="you@example.com",
    help="We use this to link your subscription, upload limits, and summaries.",
)

col_email_btn, col_email_msg = st.columns([0.25, 0.75])

with col_email_btn:
    save_clicked = st.button("Save email", type="primary")

if save_clicked:
    if not email:
        st.error("Please enter an email address first.")
    else:
        st.session_state["user_email"] = email
        with col_email_msg:
            st.success(
                "Email saved. **Next: choose a plan below (Step 2)** to open secure "
                "checkout. After payment, you’ll be returned here and can continue "
                "on to **Upload Data (Step 3)**."
            )

# Always show current plan info if we have an email
subscription = get_subscription(email)
current_plan = subscription.get("plan", "free")

if current_plan == "free":
    st.info(
        "Current status: **Free plan** – you can try the tool with lower limits. "
        "Upgrade below for higher limits and richer summaries."
    )
else:
    plan_name = current_plan.capitalize()
    st.success(
        f"Current status: **{plan_name} plan** is active for **{email or 'this email'}**. "
        "You can start using your higher limits on the **Upload Data** page."
    )

st.divider()

# ----------------------------- STEP 2: PLANS -------------------------

st.markdown("### Step 2 – Choose a plan")

plans_cols = st.columns(3)
plan_keys = ["basic", "pro", "enterprise"]

for col, key in zip(plans_cols, plan_keys):
    cfg = PLAN_CONFIG[key]
    with col:
        st.subheader(cfg["name"])
        st.caption(cfg["price"])
        st.markdown("\n".join([f"- {line}" for line in cfg["description"]]))

        if current_plan == key:
            st.button(
                "Current plan",
                disabled=True,
                key=f"{key}_current_btn",
            )
        else:
            btn_label = f"Choose {cfg['name']}"
            if st.button(btn_label, key=f"{key}_choose_btn"):
                if not email:
                    st.error("Please enter and save your email above first (Step 1).")
                else:
                    checkout_url = create_checkout_session(email=email, plan_id=key)
                    if checkout_url:
                        st.experimental_rerun()  # ensure state is flushed
                        st.markdown(
                            f'<meta http-equiv="refresh" content="0; url={checkout_url}"/>',
                            unsafe_allow_html=True,
                        )

st.markdown(
    "After a successful checkout, you’ll be redirected back here with a confirmation "
    "message at the top of the page. At that point you can continue to **Step 3**."
)

st.divider()

# ----------------------------- STEP 3: USE THE TOOL ------------------

st.markdown("### Step 3 – Start using your plan")

st.markdown(
    """
1. Go to the **Upload Data** page (link below).
2. Enter the **same email** you used here.
3. Upload a report or paste your content.
4. Click **Generate Business Summary** to create a client-ready summary.
"""
)

st.markdown("[Open Upload Data →](/Upload_Data)")
