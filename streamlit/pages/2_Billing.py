import streamlit as st
import requests
import time
from urllib.parse import urlparse, parse_qs

BACKEND_URL = st.secrets.get("BACKEND_URL")

st.set_page_config(page_title="Billing & Plans")

st.title("Billing & Plans")

# ---------------------------
# Parse URL query params
# ---------------------------
query_params = st.experimental_get_query_params()
status = query_params.get("status", [""])[0]

# ---------------------------
# Helper: check subscription
# ---------------------------
def check_subscription(email: str):
    try:
        r = requests.post(
            f"{BACKEND_URL}/subscription-status",
            json={"email": email},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        return None
    except:
        return None


# ---------------------------
# Success banner from Stripe
# ---------------------------
if status == "success":
    st.success("Checkout complete! Activating your plan…")
    st.info("Please wait a moment while we verify your subscription.")

    # Try to read email from cookies/session
    email_key = "user_email"
    email = st.session_state.get(email_key)

    if not email:
        st.warning("Please enter your email so we can activate your subscription.")
    else:
        placeholder = st.empty()
        for _ in range(20):  # ~10 seconds
            sub = check_subscription(email)
            if sub and sub["plan"] != "free":
                st.success(f"Your {sub['plan'].capitalize()} plan is active!")
                st.button("Go to Upload Data →", on_click=lambda: st.switch_page("1_Upload_Data.py"))
                st.stop()
            time.sleep(0.5)

        st.error("Still activating your plan… Try again in a moment.")
        st.stop()


# ---------------------------
# Normal Billing Page
# ---------------------------
st.subheader("Step 1 – Add your email")

email = st.text_input("Email address", key="billing_email")

if st.button("Save email & check plan"):
    st.session_state["user_email"] = email
    sub = check_subscription(email)

    if not sub:
        st.error("Could not reach backend. Try again shortly.")
        st.stop()

    if sub["plan"] == "free":
        st.info("No active subscription found yet.")
    else:
        st.success(f"You're on the {sub['plan'].capitalize()} plan!")
        st.button("Go to Upload Data →", on_click=lambda: st.switch_page("1_Upload_Data.py"))
        st.stop()


st.info("Status: Free plan. We haven't detected a subscription yet. You can upgrade below.")

# ---------------------------
# Step 2 – Choose plan
# ---------------------------
st.subheader("Step 2 – Choose a plan")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Basic\n$9.99 / month")
    st.markdown("- Upload up to **5 documents per month**")
    if st.button("Choose Basic"):
        email = st.session_state.get("user_email")
        if not email:
            st.error("Enter and save your email above first.")
        else:
            # Create checkout session
            r = requests.post(f"{BACKEND_URL}/create-checkout-session",
                              json={"plan": "basic", "email": email})
            if r.status_code == 200:
                url = r.json()["checkout_url"]
                st.markdown(f"[Click here to subscribe →]({url})")
            else:
                st.error(f"Checkout failed: {r.text}")


with col2:
    st.markdown("### Pro\n$19.99 / month")
    st.markdown("- Upload up to **30 documents per month**")
    if st.button("Choose Pro"):
        email = st.session_state.get("user_email")
        if not email:
            st.error("Enter and save your email above first.")
        else:
            r = requests.post(f"{BACKEND_URL}/create-checkout-session",
                              json={"plan": "pro", "email": email})
            if r.status_code == 200:
                url = r.json()["checkout_url"]
                st.markdown(f"[Click here to subscribe →]({url})")
            else:
                st.error(f"Checkout failed: {r.text}")


with col3:
    st.markdown("### Enterprise\n$39.99 / month")
    st.markdown("- **Unlimited uploads**")
    if st.button("Choose Enterprise"):
        email = st.session_state.get("user_email")
        if not email:
            st.error("Enter and save your email above first.")
        else:
            r = requests.post(f"{BACKEND_URL}/create-checkout-session",
                              json={"plan": "enterprise", "email": email})
            if r.status_code == 200:
                url = r.json()["checkout_url"]
                st.markdown(f"[Click here to subscribe →]({url})")
            else:
                st.error(f"Checkout failed: {r.text}")
