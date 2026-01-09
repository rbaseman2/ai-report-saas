import os
import time
import requests
import streamlit as st
import streamlit.components.v1 as components

# ============================================================
# Billing & Subscription (STABLE)
# - Check current plan
# - Create Stripe Checkout session
# - Auto-redirect to Stripe Checkout (JS) + fallback button
# - After successful checkout: show confirmation + link to Upload Data
# ============================================================

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    BACKEND_URL = "http://127.0.0.1:8000"

SUB_STATUS_ENDPOINT = f"{BACKEND_URL}/subscription-status"
CREATE_SESSION_ENDPOINT = f"{BACKEND_URL}/create-checkout-session"

st.set_page_config(page_title="Billing & Subscription", page_icon="💳", layout="wide")

def _get_query_params() -> dict:
    try:
        return dict(st.query_params)  # Streamlit >= 1.30
    except Exception:
        return st.experimental_get_query_params()  # older Streamlit

def _qp_get(qp: dict, key: str, default: str = "") -> str:
    v = qp.get(key, default)
    if isinstance(v, list):
        return v[0] if v else default
    return v if v is not None else default

def call_subscription_status(email: str) -> dict:
    r = requests.get(SUB_STATUS_ENDPOINT, params={"email": email}, timeout=30)
    r.raise_for_status()
    return r.json()

def call_create_checkout(email: str, plan: str) -> dict:
    r = requests.post(
        CREATE_SESSION_ENDPOINT,
        json={"email": email, "plan": plan},
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()

def js_redirect(url: str):
    safe = url.replace("\\", "\\\\").replace("'", "\\'")
    components.html(
        f"""
        <script>
        (function() {{
          var u = '{safe}';
          try {{ window.location.replace(u); }} catch(e) {{}}
          try {{ window.top.location.href = u; }} catch(e) {{}}
          try {{ window.open(u, '_self'); }} catch(e) {{}}
        }})();
        </script>
        """,
        height=0,
    )

if "billing_email" not in st.session_state:
    st.session_state.billing_email = ""
if "checkout_url" not in st.session_state:
    st.session_state.checkout_url = ""
if "selected_plan" not in st.session_state:
    st.session_state.selected_plan = ""
if "redirect_fired" not in st.session_state:
    st.session_state.redirect_fired = False

qp = _get_query_params()
status = _qp_get(qp, "status", "").lower()
session_id = _qp_get(qp, "session_id", "")

st.title("Billing & Subscription")

# -----------------------------
# Post-checkout message
# -----------------------------
if status == "success":
    st.success("✅ Payment successful — your subscription is now active.")

    # Try to show plan
    if st.session_state.billing_email:
        try:
            info = call_subscription_status(st.session_state.billing_email)
            plan = (info or {}).get("plan") or (info or {}).get("current_plan") or "active"
            st.info(f"Current plan: **{plan}**")
        except Exception:
            pass

    st.markdown("### Next step")
    st.write("Go to **Upload Data** to upload your PDF and generate a summary.")
    try:
        st.page_link("pages/1_Upload_Data.py", label="➡️ Go to Upload Data", icon="📄")
    except Exception:
        st.info("Use the left navigation and click **Upload Data**.")
    st.caption("If you don't see your plan update immediately, click **Check current plan** below.")
    st.divider()

# -----------------------------
# Step 1
# -----------------------------
st.subheader("Step 1 — Enter your email")

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.billing_email,
    placeholder="you@example.com",
)

colA, colB = st.columns([1, 2])
with colA:
    check_clicked = st.button("Check current plan")
with colB:
    status_placeholder = st.empty()

if email:
    st.session_state.billing_email = email.strip()

if check_clicked:
    if not st.session_state.billing_email:
        status_placeholder.error("Please enter your billing email first.")
    else:
        try:
            info = call_subscription_status(st.session_state.billing_email)
            sub_status = (info or {}).get("status", "unknown")
            plan = (info or {}).get("plan") or (info or {}).get("current_plan") or "none"
            status_placeholder.success(f"Status: {sub_status} | Current plan: {plan}")
        except requests.HTTPError as e:
            try:
                status_placeholder.error(f"Could not check subscription. {e.response.json()}")
            except Exception:
                status_placeholder.error(f"Could not check subscription. {e}")
        except Exception as e:
            status_placeholder.error(f"Could not check subscription. {e}")

st.divider()

# -----------------------------
# Step 2
# -----------------------------
st.subheader("Step 2 — Compare plans & upgrade")
st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

plan_cols = st.columns(3)

PLANS = [
    ("basic", "Basic", "$9.99 / month", [
        "Up to 20 reports / month",
        "Up to 400k characters / month",
        "Executive summaries + key insights",
    ]),
    ("pro", "Pro", "$19.99 / month", [
        "Up to 75 reports / month",
        "Up to 1.5M characters / month",
        "Action items, risks, and opportunity insights",
    ]),
    ("enterprise", "Enterprise", "$39.99 / month", [
        "Up to 250 reports / month",
        "Up to 5M characters / month",
        "Team accounts, shared templates, & premium support",
    ]),
]

selected_plan = None
for i, (key, title, price, bullets) in enumerate(PLANS):
    with plan_cols[i]:
        st.markdown(f"### {title}")
        st.write(price)
        for b in bullets:
            st.write(f"• {b}")
        if st.button(f"Choose {title}", key=f"choose_{key}"):
            selected_plan = key

if selected_plan:
    if not st.session_state.billing_email:
        st.error("Please enter your billing email above before choosing a plan.")
    else:
        st.session_state.selected_plan = selected_plan
        st.session_state.redirect_fired = False
        st.session_state.checkout_url = ""

        st.info(f"Selected plan: **{selected_plan}**. Creating Stripe Checkout session...")

        try:
            payload = call_create_checkout(st.session_state.billing_email, selected_plan)
            checkout_url = payload.get("url") or payload.get("checkout_url") or ""
            if not checkout_url:
                st.error(f"Checkout session created but no URL was returned: {payload}")
            else:
                st.session_state.checkout_url = checkout_url

                # Best-effort auto redirect
                if not st.session_state.redirect_fired:
                    st.session_state.redirect_fired = True
                    st.success("Redirecting to Stripe Checkout…")
                    js_redirect(checkout_url)
                    time.sleep(0.2)

                st.caption("If you are not redirected automatically (browser redirect blocks), click below:")
                st.link_button("Open Stripe Checkout", checkout_url)

        except requests.HTTPError as e:
            try:
                st.error(f"Checkout session failed: {e.response.json()}")
            except Exception:
                st.error(f"Checkout session failed: {e}")
        except Exception as e:
            st.error(f"Checkout session failed: {e}")

st.caption("Coupons/promo codes are entered on the Stripe Checkout page (if enabled in Stripe).")
