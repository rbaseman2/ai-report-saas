import os
import requests
import streamlit as st
from datetime import datetime

# ============================================
# CONFIG
# ============================================

# Read backend API URL from Render Environment Variables
BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com"  # fallback default
)

st.title("Billing & Subscription")

st.write(
    "Pick the plan that best fits your workload. "
    "You can upgrade later as your needs grow."
)

# ============================================
# STEP 1 – ENTER EMAIL
# ============================================

st.subheader("Step 1 – Enter your email")

email = st.text_input("Billing email (used to associate your subscription)")

if st.button("Save email & check current plan"):
    if not email:
        st.error("Please enter an email.")
    else:
        try:
            response = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": email})
            if response.status_code == 200:
                data = response.json()
                if data.get("active"):
                    st.success(
                        f"Active subscription found: **{data['plan']}**, "
                        f"renews on {datetime.fromtimestamp(data['current_period_end']).strftime('%B %d, %Y')}."
                    )
                else:
                    st.info("No active subscription found for this email.")
            else:
                st.error(f"Backend error: {response.text}")
        except Exception as e:
            st.error(f"Error contacting backend: {e}")

st.markdown("---")

# ============================================
# STEP 2 – COMPARE PLANS
# ============================================

st.subheader("Step 2 – Compare plans & upgrade")

PLAN_DETAILS = {
    "basic": {
        "price": "$9.99 / month",
        "features": [
            "Up to 20 reports / month",
            "Up to 400k characters / month",
            "Executive summaries + key insights",
        ],
    },
    "pro": {
        "price": "$19.99 / month",
        "features": [
            "Up to 75 reports / month",
            "Up to 1.5M characters / month",
            "Action items, risks, and opportunity insights",
        ],
    },
    "enterprise": {
        "price": "$39.99 / month",
        "features": [
            "Up to 250 reports / month",
            "Up to 5M characters / month",
            "Team accounts, shared templates, & premium support",
        ],
    },
}

cols = st.columns(3)

# ============================================
# PLAN BOXES
# ============================================

def draw_plan(col, plan_key, plan_data):
    with col:
        st.markdown(f"### {plan_key.capitalize()}")
        st.write(plan_data["price"])
        for feat in plan_data["features"]:
            st.write(f"- {feat}")

        if st.button(f"Choose {plan_key.capitalize()}"):
            if not email:
                st.error("Please enter your email above before selecting a plan.")
                return

            payload = {
                "email": email,
                "plan": plan_key,
            }

            try:
                r = requests.post(f"{BACKEND_URL}/create-checkout-session", json=payload)

                if r.status_code == 200:
                    checkout_url = r.json().get("checkout_url")
                    if checkout_url:
                        st.success("Redirecting to Stripe Checkout...")
                        st.markdown(f"[Click here if not redirected automatically]({checkout_url})")
                        st.experimental_set_query_params()
                        st.write(
                            f"<meta http-equiv='refresh' content='0; url={checkout_url}'>",
                            unsafe_allow_html=True
                        )
                    else:
                        st.error("Backend did not return a checkout URL.")
                else:
                    st.error(f"Checkout error: {r.text}")

            except Exception as e:
                st.error(f"Failed to create checkout session: {e}")

# Draw plans
draw_plan(cols[0], "basic", PLAN_DETAILS["basic"])
draw_plan(cols[1], "pro", PLAN_DETAILS["pro"])
draw_plan(cols[2], "enterprise", PLAN_DETAILS["enterprise"])

st.markdown("---")

st.write(
    "After you subscribe, return to the **Upload Data** tab to start generating "
    "client-ready summaries from your reports."
)
