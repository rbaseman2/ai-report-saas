import sys, pathlib, os, requests, streamlit as st
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.append(str(ROOT))
from app.entitlements import has_feature  # optional

st.set_page_config(page_title="Billing", page_icon="💳")
st.title("Billing")
st.caption("Choose a plan, manage subscription, etc.")

if "user_email" not in st.session_state:
    st.session_state["user_email"] = "test@example.com"
email = st.session_state["user_email"]

BACKEND_URL       = os.environ.get("BACKEND_URL", "http://localhost:8001")
PRICE_BASIC       = os.environ.get("PRICE_BASIC", "price_basic_missing")
PRICE_PRO         = os.environ.get("PRICE_PRO", "price_pro_missing")
PRICE_ENTERPRISE  = os.environ.get("PRICE_ENTERPRISE", "price_enterprise_missing")

# Health check
try:
    requests.get(f"{BACKEND_URL}/health", timeout=3)
except Exception:
    st.error("Backend is offline. Start uvicorn or set BACKEND_URL correctly.")
    st.stop()

with st.expander("Debug (you can hide this later)", expanded=False):
    st.write({
        "email": email,
        "BACKEND_URL": BACKEND_URL,
        "PRICE_BASIC": PRICE_BASIC,
        "PRICE_PRO": PRICE_PRO,
        "PRICE_ENTERPRISE": PRICE_ENTERPRISE,  # <-- show it
    })

def redirect_now(url: str):
    st.markdown(f'<script>window.location.href="{url}";</script>', unsafe_allow_html=True)
    st.link_button("Continue to Stripe Checkout", url); st.stop()

st.divider(); st.subheader("Plans")

# make 3 columns
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Basic\n$9.99/mo\nIncludes: core features")
    if st.button("Choose Basic", type="primary"):
        r = requests.post(f"{BACKEND_URL}/create-checkout-session",
                          json={"price_id": PRICE_BASIC, "email": email}, timeout=20)
        st.error(f"Checkout error: HTTP {r.status_code} — {r.text}") if not r.ok else redirect_now(r.json()["url"])

with col2:
    st.markdown("### Pro\n$29.99/mo\nIncludes: premium reports, bulk exports")
    pro_unlocked = has_feature(email, "premium_reports")
    if st.button("Choose Pro", disabled=pro_unlocked):
        r = requests.post(f"{BACKEND_URL}/create-checkout-session",
                          json={"price_id": PRICE_PRO, "email": email}, timeout=20)
        st.error(f"Checkout error: HTTP {r.status_code} — {r.text}") if not r.ok else redirect_now(r.json()["url"])
    if pro_unlocked: st.caption("Already on Pro ✔")

with col3:
    st.markdown("### Enterprise\n$99.99/mo\nIncludes: everything in Pro + priority support")
    ent_unlocked = has_feature(email, "enterprise") if 'has_feature' in globals() else False
    if st.button("Choose Enterprise", disabled=ent_unlocked):
        r = requests.post(f"{BACKEND_URL}/create-checkout-session",
                          json={"price_id": PRICE_ENTERPRISE, "email": email}, timeout=20)
        st.error(f"Checkout error: HTTP {r.status_code} — {r.text}") if not r.ok else redirect_now(r.json()["url"])
    if ent_unlocked: st.caption("Already on Enterprise ✔")

st.divider(); st.subheader("Manage subscription")
if st.button("Open customer portal"):
    r = requests.post(f"{BACKEND_URL}/create-portal-session",
                      json={"email": email}, timeout=20)
    st.error(f"Portal error: HTTP {r.status_code} — {r.text}") if not r.ok else redirect_now(r.json()["url"])
