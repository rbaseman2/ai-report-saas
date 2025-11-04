import sys, pathlib, os, requests, streamlit as st
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.append(str(ROOT))
from app.entitlements import has_feature  # or get_plan_for_email if you have it

st.set_page_config(page_title="Billing", page_icon="💳")
st.title("Billing")
st.caption("Choose a plan, manage subscription, etc.")

if "user_email" not in st.session_state:
    st.session_state["user_email"] = "test@example.com"
email = st.session_state["user_email"]

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")
PRICE_BASIC = os.environ.get("PRICE_BASIC", "price_...basic")
PRICE_PRO   = os.environ.get("PRICE_PRO",   "price_...pro")

# Health check
try:
    requests.get(f"{BACKEND_URL}/health", timeout=3)
except Exception:
    st.error("Backend is offline. Start uvicorn or set BACKEND_URL correctly.")
    st.stop()

with st.expander("Debug (you can hide this later)", expanded=False):
    st.write({"email": email, "BACKEND_URL": BACKEND_URL,
              "PRICE_BASIC": PRICE_BASIC, "PRICE_PRO": PRICE_PRO})

def redirect_now(url: str):
    st.markdown(f'<script>window.location.href="{url}";</script>', unsafe_allow_html=True)
    st.link_button("Continue", url); st.stop()

st.divider(); st.subheader("Plans")

col1, col2 = st.columns(2)
with col1:
    st.markdown("### Basic\n$9/mo\nIncludes: core features")
    if st.button("Choose Basic", type="primary"):
        r = requests.post(f"{BACKEND_URL}/create-checkout-session",
                          json={"price_id": PRICE_BASIC, "email": email}, timeout=20)
        st.error(f"Checkout error: HTTP {r.status_code} — {r.text}") if not r.ok else redirect_now(r.json()["url"])

with col2:
    st.markdown("### Pro\n$29/mo\nIncludes: premium reports, bulk exports")
    pro_unlocked = has_feature(email, "premium_reports")
    if st.button("Choose Pro", disabled=pro_unlocked):
        r = requests.post(f"{BACKEND_URL}/create-checkout-session",
                          json={"price_id": PRICE_PRO, "email": email}, timeout=20)
        st.error(f"Checkout error: HTTP {r.status_code} — {r.text}") if not r.ok else redirect_now(r.json()["url"])
    if pro_unlocked:
        st.caption("Already on Pro for this email ✔︎")

st.divider(); st.subheader("Manage subscription")
if st.button("Open customer portal"):
    r = requests.post(f"{BACKEND_URL}/create-portal-session",
                      json={"email": email}, timeout=20)
    st.error(f"Portal error: HTTP {r.status_code} — {r.text}") if not r.ok else redirect_now(r.json()["url"])
