import os
import time
import requests
import streamlit as st
import streamlit.components.v1 as components

# ------------------------------------------------------------
# Billing & Subscription (Streamlit page)
# ------------------------------------------------------------
# Goals:
#  - User enters billing email (stored in session_state)
#  - "Check current plan" calls backend /subscription-status?email=...
#  - Choosing a plan calls backend POST /create-checkout-session
#  - Auto-redirects to Stripe Checkout (same-tab) with a fallback button
#  - After Stripe returns with ?status=success, show a clear "Continue to Upload Data" message
# ------------------------------------------------------------

st.set_page_config(page_title="Billing & Subscription", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")


def require_backend() -> None:
    if not BACKEND_URL:
        st.error("BACKEND_URL environment variable is not set.")
        st.stop()


def get_query_params() -> dict:
    """Compatible across Streamlit versions."""
    try:
        qp = dict(st.query_params)  # Streamlit >= 1.30-ish
    except Exception:
        qp = st.experimental_get_query_params()  # older Streamlit
    return qp or {}


def first_param(qp: dict, key: str):
    v = qp.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def api_get(path: str, params: dict | None = None, timeout: int = 20):
    require_backend()
    url = f"{BACKEND_URL}{path}"
    return requests.get(url, params=params, timeout=timeout)


def api_post(path: str, payload: dict, timeout: int = 30):
    require_backend()
    url = f"{BACKEND_URL}{path}"
    return requests.post(url, json=payload, timeout=timeout)


def redirect_to(url: str) -> None:
    """Best-effort redirect in the same tab."""
    # 1) JS redirect (best)
    components.html(
        f"""
        <script>
          window.top.location.href = {url!r};
        </script>
        """,
        height=0,
    )
    # 2) Meta refresh fallback
    st.markdown(f"<meta http-equiv='refresh' content='0; url={url}'>", unsafe_allow_html=True)
    # 3) Stop to avoid rerun loops
    st.stop()


# -----------------------------
# Session state defaults
# -----------------------------
if "billing_email" not in st.session_state:
    st.session_state.billing_email = ""
if "checkout_url" not in st.session_state:
    st.session_state.checkout_url = ""
if "checkout_plan" not in st.session_state:
    st.session_state.checkout_plan = ""
if "checkout_creating" not in st.session_state:
    st.session_state.checkout_creating = False
if "subscription_status" not in st.session_state:
    st.session_state.subscription_status = None  # dict or None


# -----------------------------
# Handle Stripe return parameters
# -----------------------------
qp = get_query_params()
status = first_param(qp, "status")
session_id = first_param(qp, "session_id")

st.title("Billing & Subscription")

# If Stripe returned success/cancel, show a focused message at the top.
if status == "success":
    st.success("✅ Checkout complete! Your subscription is active.")

    if session_id:
        st.caption(f"Checkout session: {session_id}")

    st.markdown("### Next step")
    st.write("Continue to **Upload Data** to generate your first report.")

    if st.button("Go to Upload Data →", type="primary"):
        st.switch_page("pages/1_🏁_Upload_Data.py")

    st.stop()

    # Try to fetch plan/status using the stored email (if present) to show the plan.
    email_for_status = st.session_state.billing_email
    if email_for_status:
        try:
            r = api_get("/subscription-status", params={"email": email_for_status}, timeout=20)
            if r.ok:
                st.session_state.subscription_status = r.json()
        except Exception:
            pass

    plan_name = None
    if isinstance(st.session_state.subscription_status, dict):
        plan_name = st.session_state.subscription_status.get("plan") or st.session_state.subscription_status.get("current_plan")

    if plan_name:
        st.info(f"You're now subscribed to **{plan_name}**. You can start using the app right away.")

    st.markdown("### Next step")
    st.write("Go to **Upload Data** to upload a document and generate your summary.")

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("Continue to Upload Data →", type="primary"):
            try:
                st.switch_page("pages/1_Upload_Data.py")
            except Exception:
                st.info("Use the left sidebar to open **Upload Data**.")
    with col2:
        st.caption("If you don’t see your plan update immediately, wait a few seconds and click “Check current plan” below.")

    st.divider()

elif status == "cancel":
    st.warning("Checkout was cancelled. You can select a plan again below.")
    st.divider()


# -----------------------------
# Step 1: Email + check status
# -----------------------------
st.subheader("Step 1 — Enter your email")

billing_email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.billing_email,
    placeholder="you@example.com",
)

# Persist immediately (so the success screen can re-use it)
st.session_state.billing_email = (billing_email or "").strip()

colA, colB = st.columns([1, 3])
with colA:
    check_clicked = st.button("Check current plan")
with colB:
    status_box = st.empty()

if check_clicked:
    if not st.session_state.billing_email:
        status_box.error("Please enter your email first.")
    else:
        try:
            r = api_get("/subscription-status", params={"email": st.session_state.billing_email})
            if r.ok:
                st.session_state.subscription_status = r.json()
            else:
                status_box.error(f"Could not check subscription. {r.text}")
        except Exception as e:
            status_box.error(f"Error checking subscription: {e}")

# Show status if we have it
if isinstance(st.session_state.subscription_status, dict):
    plan = st.session_state.subscription_status.get("plan") or st.session_state.subscription_status.get("current_plan") or "none"
    state = st.session_state.subscription_status.get("status") or "unknown"
    status_box.success(f"Status: {state} | Current plan: {plan}")

st.divider()

# -----------------------------
# Step 2: Plans
# -----------------------------
st.subheader("Step 2 — Compare plans & upgrade")
st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

plans = [
    ("basic", "Basic", "$9.99 / month", ["Up to 20 reports / month", "Up to 400k characters / month", "Executive summaries + key insights"]),
    ("pro", "Pro", "$19.99 / month", ["Up to 75 reports / month", "Up to 1.5M characters / month", "Action items, risks, and opportunity insights"]),
    ("enterprise", "Enterprise", "$39.99 / month", ["Up to 250 reports / month", "Up to 5M characters / month", "Team accounts, shared templates, & premium support"]),
]

c1, c2, c3 = st.columns(3)

cols = [c1, c2, c3]
clicked_plan_key = None

for (plan_key, plan_label, price, bullets), col in zip(plans, cols):
    with col:
        st.markdown(f"### {plan_label}")
        st.markdown(f"**{price}**")
        for b in bullets:
            st.write(f"• {b}")
        if st.button(f"Choose {plan_label}", key=f"choose_{plan_key}"):
            clicked_plan_key = plan_key

message_area = st.empty()

# Create checkout session on click (only once per click)
if clicked_plan_key:
    if not st.session_state.billing_email:
        message_area.error("Please enter your billing email first (Step 1).")
    else:
        st.session_state.checkout_creating = True
        st.session_state.checkout_plan = clicked_plan_key
        st.session_state.checkout_url = ""

        message_area.info(f"Selected plan: **{clicked_plan_key}**. Creating Stripe Checkout session...")

        try:
            r = api_post("/create-checkout-session", {"plan": clicked_plan_key, "email": st.session_state.billing_email})
            if not r.ok:
                message_area.error(f"Could not create checkout session. {r.text}")
                st.session_state.checkout_creating = False
            else:
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                checkout_url = data.get("url") or data.get("checkout_url")
                if not checkout_url:
                    # Some backends return plain text
                    checkout_url = r.text.strip()

                st.session_state.checkout_url = checkout_url
                st.session_state.checkout_creating = False

                # Auto-redirect immediately
                message_area.success("Redirecting to Stripe Checkout…")
                time.sleep(0.2)
                redirect_to(checkout_url)

        except Exception as e:
            st.session_state.checkout_creating = False
            message_area.error(f"Error creating checkout session: {e}")

# If we have a checkout URL (e.g., user came back and the redirect was blocked),
# show a clear fallback button.
if st.session_state.checkout_url:
    st.info("If you are not redirected automatically, use the button below.")
    st.link_button("Open Stripe Checkout", st.session_state.checkout_url)

st.caption("Coupons/promo codes are entered on the Stripe Checkout page (if enabled in Stripe).")
