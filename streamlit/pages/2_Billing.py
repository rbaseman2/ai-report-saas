
import os
import requests
import streamlit as st

# ---------- Config ----------

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

st.set_page_config(
    page_title="Billing & Subscription – AI Report",
    page_icon="💳",
    layout="centered",
)

# ---------- Small helpers ----------


def get_plan_display(plan: str) -> str:
    plan = (plan or "").lower()
    if plan == "basic":
        return "Basic"
    if plan == "pro":
        return "Pro"
    if plan == "enterprise":
        return "Enterprise"
    return "Free"


def fetch_subscription(email: str):
    """
    Call backend /subscription-status and normalize the response.

    Expected backend response on success:
        {
          "plan": "free" | "basic" | "pro" | "enterprise",
          "max_documents": int,
          "max_chars": int
        }

    If backend returns 404 -> treat as free plan.
    """
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=20,
        )

        if resp.status_code == 404:
            return {
                "plan": "free",
                "max_documents": 5,
                "max_chars": 200_000,
            }

        resp.raise_for_status()
        data = resp.json() or {}

        return {
            "plan": data.get("plan", "free"),
            "max_documents": data.get("max_documents", 5),
            "max_chars": data.get("max_chars", 200_000),
        }

    except Exception as exc:
        st.error(f"Error while checking subscription: {exc}")
        # Fall back to Free so the app still works
        return {
            "plan": "free",
            "max_documents": 5,
            "max_chars": 200_000,
        }


def start_checkout(email: str, plan: str):
    """
    Start Stripe Checkout by calling backend /create-checkout-session.

    Expected backend response:
        { "checkout_url": "https://checkout.stripe.com/..." }
    """
    try:
        with st.spinner("Contacting billing server…"):
            resp = requests.post(
                f"{BACKEND_URL}/create-checkout-session",
                json={"email": email, "plan": plan},
                timeout=40,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            url = data.get("checkout_url")

        if not url:
            st.error("Backend did not return a checkout URL.")
            return

        st.success("Checkout session created.")

        # Store so we can show it elsewhere if we want
        st.session_state["last_checkout_url"] = url

        st.info(
            "Click the button below to open Stripe Checkout in a new tab "
            "and complete your purchase."
        )

        # Button that opens Stripe checkout
        st.link_button("Open Stripe Checkout", url, type="primary")

    except Exception as exc:
        st.error(f"Network error starting checkout: {exc}")



# ---------- Page UI ----------

st.title("Billing & Subscription")
st.caption(
    "Choose a plan that matches how often you need to summarize reports. "
    "You can upgrade at any time as your workload grows."
)

if not BACKEND_URL:
    st.error(
        "BACKEND_URL environment variable is not set for the Streamlit app. "
        "Set it in Render → ai-report-saas → Environment so billing can talk "
        "to the backend."
    )
    st.stop()

# Keep a clean namespace in session_state
if "billing_email" not in st.session_state:
    st.session_state["billing_email"] = ""
if "plan_info" not in st.session_state:
    st.session_state["plan_info"] = {
        "plan": "free",
        "max_documents": 5,
        "max_chars": 200_000,
    }

# ---------- Step 1 – Email ----------

st.subheader("Step 1 – Your billing email")

with st.container():
    st.write(
        "We’ll use this email to link your subscription, upload limits, and "
        "summaries. Use the **same email** you use at checkout."
    )

    email = st.text_input(
        "Billing email",
        value=st.session_state["billing_email"],
        placeholder="you@company.com",
    )

    check_btn = st.button("Save email & check current plan", type="primary")

    if check_btn:
        if not email.strip():
            st.error("Please enter an email address first.")
        else:
            st.session_state["billing_email"] = email.strip()
            st.session_state["plan_info"] = fetch_subscription(
                st.session_state["billing_email"]
            )

# ---------- Current plan card ----------

plan_info = st.session_state["plan_info"]
current_plan_label = get_plan_display(plan_info.get("plan"))

with st.container():
    st.markdown("### Current plan")

    st.info(
        f"**Status:** {current_plan_label} plan  \n"
        f"You can upload up to **{plan_info['max_documents']} reports per month** "
        f"and a total of about **{plan_info['max_chars']:,} characters**."
    )

    st.caption(
        "Your plan controls how many reports you can upload and the maximum "
        "length we can summarize each month."
    )

# ---------- Step 2 – Compare & upgrade ----------

st.subheader("Step 2 – Compare plans & upgrade")

st.write(
    "Pick the plan that best fits your workload. "
    "You can upgrade later as your needs grow."
)

col_basic, col_pro, col_ent = st.columns(3)

with col_basic:
    st.markdown("#### Basic\n$9.99 / month")
    st.write(
        "- Up to 20 reports / month\n"
        "- Up to 400k characters / month\n"
        "- Executive summaries + key insights"
    )
    if st.button("Choose Basic", key="choose_basic"):
        if not st.session_state["billing_email"]:
            st.error("Enter and save your billing email in Step 1 first.")
        else:
            start_checkout(st.session_state["billing_email"], "basic")

with col_pro:
    st.markdown("#### Pro\n$19.99 / month")
    st.write(
        "- Up to 75 reports / month\n"
        "- Up to 1.5M characters / month\n"
        "- Action items, risks, and opportunity insights"
    )
    if st.button("Choose Pro", key="choose_pro"):
        if not st.session_state["billing_email"]:
            st.error("Enter and save your billing email in Step 1 first.")
        else:
            start_checkout(st.session_state["billing_email"], "pro")

with col_ent:
    st.markdown("#### Enterprise\n$39.99 / month")
    st.write(
        "- Up to 250 reports / month\n"
        "- Up to 5M characters / month\n"
        "- Team accounts, shared templates, & premium support"
    )
    if st.button("Choose Enterprise", key="choose_ent"):
        if not st.session_state["billing_email"]:
            st.error("Enter and save your billing email in Step 1 first.")
        else:
            start_checkout(st.session_state["billing_email"], "enterprise")

st.markdown("---")
st.caption(
    "After you subscribe, return to the **Upload Data** tab to start generating "
    "client-ready summaries from your reports."
)
