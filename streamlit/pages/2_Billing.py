import os
import streamlit as st
import requests

st.set_page_config(page_title="Billing & Subscription", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set.")
    st.stop()


# -----------------------------
# Helpers
# -----------------------------
def get_subscription_status(email: str):
    r = requests.get(
        f"{BACKEND_URL}/subscription-status",
        params={"email": email},
        timeout=20
    )
    r.raise_for_status()
    return r.json()


def create_checkout_session(email: str, plan: str):
    r = requests.post(
        f"{BACKEND_URL}/create-checkout-session",
        json={"email": email, "plan": plan},
        timeout=30
    )
    r.raise_for_status()
    return r.json()  # expects {"url": "https://checkout.stripe.com/..."}


def normalize_plan(plan: str | None):
    if not plan:
        return None
    p = str(plan).strip().lower()
    if p in ("basic", "pro", "enterprise"):
        return p
    return None


# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.markdown("## Navigation")
    try:
        st.page_link("Home.py", label="Home")
    except Exception:
        st.write("Home")

    st.page_link("pages/1_Upload_Data.py", label="Upload Data")
    st.page_link("pages/2_Billing.py", label="Billing", disabled=True)

    # If you have these pages, keep them; otherwise remove.
    # st.page_link("pages/3_Terms.py", label="Terms")
    # st.page_link("pages/4_Privacy.py", label="Privacy")


# -----------------------------
# Header + return status from checkout
# -----------------------------
st.title("Billing & Subscription")

# Handle Stripe redirect back (optional)
# Example return URL: /Billing?status=success&session_id=cs_...
qp = st.query_params
checkout_status = qp.get("status", None)
if checkout_status == "success":
    st.success("Payment successful! Your subscription is now active.")
elif checkout_status == "cancel":
    st.warning("Checkout cancelled. No changes were made.")


# -----------------------------
# Step 1 - Email + status
# -----------------------------
st.subheader("Step 1 — Enter your email")

email_default = st.session_state.get("billing_email", "")
billing_email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=email_default,
    placeholder="you@example.com"
)

col_a, col_b = st.columns([1, 3], vertical_alignment="center")
with col_a:
    check_btn = st.button("Save email & check current plan", use_container_width=True)

status_box = st.empty()

resolved_plan = None
resolved_status = "none"

if check_btn:
    email = billing_email.strip()
    st.session_state["billing_email"] = email
    if not email:
        status_box.error("Please enter a billing email.")
    else:
        try:
            sub = get_subscription_status(email)
            resolved_plan = normalize_plan(sub.get("plan")) or "basic"
            resolved_status = (sub.get("status") or "none").strip().lower()

            status_box.info(
                f"Status: **{resolved_status}**  |  Current plan: **{resolved_plan.title()}**"
            )
        except Exception as e:
            status_box.error(f"Could not check subscription. {e}")

# If user already saved email earlier, show status automatically (nice UX)
if not check_btn and st.session_state.get("billing_email"):
    try:
        sub = get_subscription_status(st.session_state["billing_email"])
        resolved_plan = normalize_plan(sub.get("plan")) or "basic"
        resolved_status = (sub.get("status") or "none").strip().lower()

        status_box.info(
            f"Status: **{resolved_status}**  |  Current plan: **{resolved_plan.title()}**"
        )
    except Exception:
        pass

st.divider()


# -----------------------------
# Step 2 - Plan cards
# -----------------------------
st.subheader("Step 2 — Compare plans & upgrade")
st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

if not st.session_state.get("billing_email"):
    st.warning("Enter and save your billing email above before selecting a plan.")

c1, c2, c3 = st.columns(3)

def plan_card(col, title, price, bullets, plan_key):
    with col:
        st.markdown(f"### {title}")
        st.markdown(f"**{price} / month**")
        for b in bullets:
            st.markdown(f"- {b}")

        btn = st.button(f"Choose {title}", key=f"choose_{plan_key}", use_container_width=True)
        if btn:
            email = (st.session_state.get("billing_email") or "").strip()
            if not email:
                st.error("Please enter a billing email in Step 1 first.")
                st.stop()

            try:
                data = create_checkout_session(email=email, plan=plan_key)
                url = data.get("url")
                if not url:
                    st.error("Checkout URL was not returned by backend.")
                    st.stop()

                # Redirect (clean + reliable)
                st.markdown(
                    f"""
                    <meta http-equiv="refresh" content="0; url={url}">
                    <p>Redirecting to checkout… If you are not redirected, <a href="{url}">click here</a>.</p>
                    """,
                    unsafe_allow_html=True
                )
                st.stop()

            except Exception as e:
                st.error(f"Could not start checkout: {e}")


plan_card(
    c1,
    "Basic",
    "$9.99",
    [
        "Up to 20 reports / month",
        "Up to 400k characters / month",
        "Executive summaries + key insights",
    ],
    "basic"
)

plan_card(
    c2,
    "Pro",
    "$19.99",
    [
        "Up to 75 reports / month",
        "Up to 1.5M characters / month",
        "Action items, risks, and opportunity insights",
    ],
    "pro"
)

plan_card(
    c3,
    "Enterprise",
    "$39.99",
    [
        "Up to 250 reports / month",
        "Up to 5M characters / month",
        "Team accounts, shared templates, & premium support",
    ],
    "enterprise"
)

st.info(
    "Coupons/promo codes are entered on the Stripe Checkout page (they will appear if enabled in your Stripe settings)."
)
