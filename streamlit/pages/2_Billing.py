import os
import streamlit as st
import requests

st.set_page_config(page_title="Billing", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set in the Streamlit service.")
    st.stop()

st.title("Billing & Subscription")

# Sidebar navigation (safe)
with st.sidebar:
    st.header("Navigation")
    try:
        st.page_link("Home.py", label="Home")
    except Exception:
        pass
    try:
        st.page_link("pages/Upload_Data.py", label="Upload Data")
    except Exception:
        pass
    st.page_link("pages/Billing.py", label="Billing", disabled=True)

# Read status params (after Stripe checkout redirect)
q = st.query_params
if q.get("status") == "success":
    st.success("Payment successful! Your subscription is now active.")
elif q.get("status") == "cancel":
    st.warning("Checkout canceled.")

st.subheader("Step 1 — Enter your email")
email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.get("billing_email", ""),
    placeholder="you@example.com",
)

colA, colB = st.columns([1, 3])
with colA:
    check = st.button("Save email & check current plan")

plan = None
status = "none"
if check:
    st.session_state["billing_email"] = email.strip()
    try:
        r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": email.strip()}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            plan = data.get("plan")
            status = data.get("status") or "none"
        else:
            st.error(f"Backend error {r.status_code}: {r.text}")
    except Exception as e:
        st.error(f"Error contacting backend: {e}")

# Display current
if "billing_email" in st.session_state and st.session_state["billing_email"].strip():
    try:
        r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": st.session_state["billing_email"]}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            plan = data.get("plan")
            status = data.get("status") or "none"
    except Exception:
        pass

st.write(f"**Status:** {status}")
st.write(f"**Current plan:** {plan if plan else 'None'}")

st.divider()
st.subheader("Step 2 — Compare plans & upgrade")

plans = [
    ("basic", "$9.99 / month", ["Up to 20 reports / month", "Up to 400k characters / month", "Executive summaries + key insights"]),
    ("pro", "$19.99 / month", ["Up to 75 reports / month", "Up to 1.5M characters / month", "Action items, risks, opportunity insights"]),
    ("enterprise", "$39.99 / month", ["Up to 250 reports / month", "Up to 5M characters / month", "Team accounts, shared templates, premium support"]),
]

cols = st.columns(3)
for i, (pname, price, bullets) in enumerate(plans):
    with cols[i]:
        st.markdown(f"### {pname.title()}\n**{price}**")
        for b in bullets:
            st.write(f"- {b}")

        if st.button(f"Choose {pname.title()}", key=f"choose_{pname}"):
            if not email.strip():
                st.error("Enter your billing email first.")
            else:
                try:
                    payload = {"email": email.strip(), "plan": pname}
                    resp = requests.post(f"{BACKEND_URL}/create-checkout-session", json=payload, timeout=30)
                    if resp.status_code != 200:
                        st.error(f"Checkout error {resp.status_code}: {resp.text}")
                    else:
                        url = resp.json().get("url")
                        if not url:
                            st.error("Checkout URL was not returned by backend.")
                        else:
                            # ✅ Redirect to Stripe checkout
                            st.markdown(f"[Click here to continue to checkout]({url})")
                            st.info("If you are not redirected automatically, click the link above.")
                            st.components.v1.html(f"<script>window.location.href='{url}';</script>", height=0)
                except Exception as e:
                    st.error(f"Failed to create checkout session: {e}")
