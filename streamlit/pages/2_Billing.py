import os
import time
import requests
import streamlit as st
import streamlit.components.v1 as components

# -----------------------------
# Config
# -----------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

if not BACKEND_URL:
    st.error("Backend is not configured.")
    st.stop()

# -----------------------------
# Handle Stripe return (success / cancel)
# -----------------------------
qp = {}
try:
    qp = st.query_params
    status = qp.get("status")
    session_id = qp.get("session_id")
except Exception:
    qp = st.experimental_get_query_params()
    status = (qp.get("status", [None]) or [None])[0]
    session_id = (qp.get("session_id", [None]) or [None])[0]

if status == "success":
    st.success("✅ Payment successful! Your subscription is now active.")
    st.markdown("### 👉 Next step")
    st.markdown("Go to **Upload Data** to upload a PDF and generate your summary.")
    st.markdown("➡️ **[Go to Upload Data](/Upload_Data)**")

    if session_id:
        st.caption(f"Checkout session: {session_id}")

    # Clear query params so refresh doesn't repeat success state
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()

    st.stop()

elif status == "cancel":
    st.warning("Checkout was canceled. You may choose a plan below.")

# -----------------------------
# Page UI
# -----------------------------
st.title("Billing & Subscription")

# -----------------------------
# Step 1 – Email
# -----------------------------
st.subheader("Step 1 — Enter your email")

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.get("billing_email", ""),
)

if email:
    st.session_state["billing_email"] = email

if st.button("Check current plan"):
    if not email:
        st.error("Please enter an email address.")
    else:
        try:
            r = requests.get(
                f"{BACKEND_URL}/subscription-status",
                params={"email": email},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            st.success(
                f"Status: {data.get('status','unknown')} | "
                f"Current plan: {data.get('plan','none')}"
            )
        except Exception as e:
            st.error(f"Could not check subscription: {e}")

st.divider()

# -----------------------------
# Step 2 – Plans
# -----------------------------
st.subheader("Step 2 — Compare plans & upgrade")
st.caption("Choose a plan to continue to secure Stripe Checkout.")

PLANS = {
    "basic": {
        "label": "Basic",
        "price": "$9.99 / month",
        "features": [
            "Up to 20 reports / month",
            "Up to 400k characters / month",
            "Executive summaries + key insights",
        ],
    },
    "pro": {
        "label": "Pro",
        "price": "$19.99 / month",
        "features": [
            "Up to 75 reports / month",
            "Up to 1.5M characters / month",
            "Action items, risks, opportunity insights",
        ],
    },
    "enterprise": {
        "label": "Enterprise",
        "price": "$39.99 / month",
        "features": [
            "Up to 250 reports / month",
            "Up to 5M characters / month",
            "Team accounts, shared templates, premium support",
        ],
    },
}

cols = st.columns(3)

selected_plan = None
for col, plan_key in zip(cols, PLANS.keys()):
    plan = PLANS[plan_key]
    with col:
        st.markdown(f"### {plan['label']}")
        st.markdown(plan["price"])
        for f in plan["features"]:
            st.markdown(f"- {f}")
        if st.button(f"Choose {plan['label']}", key=f"choose_{plan_key}"):
            selected_plan = plan_key

# -----------------------------
# Create Checkout Session
# -----------------------------
if selected_plan:
    if not email:
        st.error("Please enter your billing email first.")
    else:
        st.info(f"Selected plan: **{selected_plan}**. Redirecting to Stripe Checkout…")

        try:
            resp = requests.post(
                f"{BACKEND_URL}/create-checkout-session",
                json={
                    "email": email,
                    "plan": selected_plan,
                },
                timeout=30,
            )
            resp.raise_for_status()
            checkout_url = resp.json().get("checkout_url")

            if not checkout_url:
                st.error("Checkout URL was not returned by backend.")
            else:
                # Immediate redirect (same behavior you had before)
                components.html(
                    f"""
                    <script>
                        window.location.href = "{checkout_url}";
                    </script>
                    """,
                    height=0,
                )

                st.success("Redirecting to Stripe Checkout…")
                st.markdown(
                    f"If you are not redirected automatically, "
                    f"[click here to open checkout]({checkout_url})."
                )

        except Exception as e:
            st.error(f"Failed to start checkout: {e}")
