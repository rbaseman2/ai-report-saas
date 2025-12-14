import os
import streamlit as st
import requests

st.set_page_config(page_title="Billing", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    st.error("BACKEND_URL not set.")
    st.stop()

st.title("Billing & Subscription")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Navigation")
    st.page_link("pages/1_Upload_Data.py", label="Upload Data")
    st.page_link("pages/2_Billing.py", label="Billing", disabled=True)

email = st.text_input("Billing email")

if st.button("Save email & check current plan"):
    try:
        r = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=20
        )
        r.raise_for_status()
        st.session_state["billing_email"] = email
        data = r.json()
        st.success(f"Status: {data.get('status')} | Plan: {data.get('plan') or 'basic'}")
    except Exception as e:
        st.error(e)

st.divider()
st.subheader("Upgrade")

for plan in ["basic", "pro", "enterprise"]:
    if st.button(f"Choose {plan.title()}"):
        r = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"email": email, "plan": plan},
            timeout=20
        )
        if r.status_code == 200:
            st.markdown(f"[Go to Checkout]({r.json()['url']})")
        else:
            st.error(r.text)
