import os
import time
import streamlit as st
import requests
import streamlit.components.v1 as components

# -----------------------------
# Config
# -----------------------------
st.set_page_config(page_title="Billing & Subscription", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    # sensible default for Render deployment; override with env var
    BACKEND_URL = "https://ai-report-backend-ubrx.onrender.com"

PLANS = {
    "basic": {"label": "Basic", "price": "$9.99 / month", "bullets": ["Up to 20 reports / month", "Up to 400k characters / month", "Executive summaries + key insights"]},
    "pro": {"label": "Pro", "price": "$19.99 / month", "bullets": ["Up to 75 reports / month", "Up to 1.5M characters / month", "Action items, risks, and opportunity insights"]},
    "enterprise": {"label": "Enterprise", "price": "$39.99 / month", "bullets": ["Up to 250 reports / month", "Up to 5M characters / month", "Team accounts, shared templates, & premium support"]},
}

def _safe_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}

def get_subscription_status(email: str):
    r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": email}, timeout=30)
    r.raise_for_status()
    return r.json()

def create_checkout_session(email: str, plan: str):
    r = requests.post(
        f"{BACKEND_URL}/create-checkout-session",
        json={"email": email, "plan": plan},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()

def _js_redirect(url: str):
    # More reliable than meta refresh across browsers / iframes.
    components.html(
        f"""
        <script>
          const u = {url!r};
          window.top.location.href = u;
        </script>
        """,
        height=0,
        width=0,
    )

# -----------------------------
# Handle return from Stripe
# -----------------------------
params = st.query_params
if params.get("status") == "success":
    st.success("Payment completed successfully.")
    st.info("Next step: upload a PDF or paste text to generate your summary.")
    if st.button("Continue to Upload Data", type="primary"):
        # Navigate to Upload page
        try:
            st.switch_page("pages/1_Upload_Data.py")
        except Exception:
            st.info("Use the left menu to open **Upload Data**.")
    st.divider()

# -----------------------------
# UI
# -----------------------------
st.title("Billing & Subscription")

st.subheader("Step 1 — Enter your email")
email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.get("billing_email", ""),
    placeholder="you@example.com",
)

col_a, col_b = st.columns([1, 2])
with col_a:
    check = st.button("Check current plan")
with col_b:
    status_placeholder = st.empty()

if email:
    st.session_state["billing_email"] = email  # used by Upload page too

if check:
    if not email:
        st.warning("Please enter a billing email first.")
    else:
        try:
            data = get_subscription_status(email)
            status = data.get("status", "none")
            plan = data.get("plan", "none")
            if status == "active":
                status_placeholder.success(f"Status: {status} | Current plan: {plan}")
            else:
                status_placeholder.info(f"Status: {status} | Current plan: {plan}")
        except requests.HTTPError as e:
            body = _safe_json(e.response) if getattr(e, "response", None) is not None else {"detail": str(e)}
            status_placeholder.error(f"Could not check subscription. {body}")
        except Exception as e:
            status_placeholder.error(f"Could not check subscription. {e}")

st.divider()

st.subheader("Step 2 — Compare plans & upgrade")
st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

c1, c2, c3 = st.columns(3)

def plan_card(container, key: str):
    p = PLANS[key]
    with container:
        st.markdown(f"### {p['label']}")
        st.markdown(p["price"])
        for b in p["bullets"]:
            st.write(f"• {b}")
        clicked = st.button(f"Choose {p['label']}", key=f"choose_{key}")
        return clicked

chosen_basic = plan_card(c1, "basic")
chosen_pro = plan_card(c2, "pro")
chosen_enterprise = plan_card(c3, "enterprise")

chosen = None
if chosen_basic: chosen = "basic"
if chosen_pro: chosen = "pro"
if chosen_enterprise: chosen = "enterprise"

if chosen:
    if not email:
        st.warning("Please enter your billing email above first.")
    else:
        st.session_state["selected_plan"] = chosen
        st.info(f"Selected plan: {chosen}. Creating Stripe Checkout session...")
        try:
            out = create_checkout_session(email=email, plan=chosen)
            checkout_url = out.get("checkout_url") or out.get("url") or out.get("checkoutUrl")
            if not checkout_url:
                st.error(f"Backend did not return a checkout URL. Response: {out}")
            else:
                st.session_state["checkout_url"] = checkout_url
                st.session_state.pop("redirect_done", None)
        except requests.HTTPError as e:
            body = _safe_json(e.response) if getattr(e, "response", None) is not None else {"detail": str(e)}
            st.error(f"Could not create checkout session. {body}")
        except Exception as e:
            st.error(f"Could not create checkout session. {e}")

# Auto-redirect once per session_state checkout_url
checkout_url = st.session_state.get("checkout_url")
if checkout_url:
    st.success("Redirecting to Stripe Checkout…")
    st.caption("If you are not redirected automatically, use the button below.")
    # Try redirect immediately via JS
    if not st.session_state.get("redirect_done"):
        st.session_state["redirect_done"] = True
        _js_redirect(checkout_url)
        # small delay to give the browser a chance
        time.sleep(0.2)

    st.link_button("Open Stripe Checkout", checkout_url)

st.caption("Coupons/promo codes are entered on the Stripe Checkout page (if enabled in Stripe).")
