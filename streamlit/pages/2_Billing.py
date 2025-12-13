import os
import json
import requests
import streamlit as st

st.set_page_config(page_title="Billing & Subscription", page_icon="💳", layout="wide")

# ---------- Config ----------
APP_VERSION = "2025-12-12 v10"  # optional: helps you confirm deploys

def get_backend_url() -> str:
    """
    Prefer env var on Render. Fall back to secrets if you still use it locally.
    """
    env_url = os.getenv("BACKEND_URL")
    if env_url and env_url.strip():
        return env_url.strip().rstrip("/")

    # Optional local fallback if you use secrets.toml in dev
    try:
        sec_url = st.secrets.get("BACKEND_URL")
        if sec_url:
            return str(sec_url).strip().rstrip("/")
    except Exception:
        pass

    # Last resort
    return "http://localhost:8000"

BACKEND_URL = get_backend_url()

# ---------- Helpers ----------
def safe_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return {"_raw": resp.text}

def create_checkout_session(email: str, plan: str):
    """
    Calls backend and returns (checkout_url, payload_json)
    Handles multiple possible keys so UI won't break if backend changes.
    """
    url = f"{BACKEND_URL}/create-checkout-session"
    payload = {"email": email, "plan": plan}

    r = requests.post(url, json=payload, timeout=30)
    data = safe_json(r)

    if r.status_code >= 400:
        raise RuntimeError(f"Backend error {r.status_code}: {data}")

    # Accept multiple possible keys (prevents 'url not returned' regressions)
    checkout_url = (
        data.get("checkout_url")
        or data.get("url")
        or data.get("checkoutUrl")
        or data.get("checkoutURL")
        or data.get("session_url")
    )
    return checkout_url, data

def get_subscription_status(email: str):
    url = f"{BACKEND_URL}/subscription-status"
    r = requests.get(url, params={"email": email}, timeout=30)
    data = safe_json(r)

    if r.status_code >= 400:
        raise RuntimeError(f"Backend error {r.status_code}: {data}")

    return data

def redirect_to(url: str):
    """
    Streamlit-safe redirect: use JS. Works reliably on hosted Streamlit.
    """
    st.markdown(
        f"""
        <script>
          window.location.href = {json.dumps(url)};
        </script>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

# ---------- UI ----------
st.title("Billing & Subscription")
st.caption(f"Billing build: {APP_VERSION}")

# Optional: show backend target for debugging
with st.expander("Debug (backend target)"):
    st.write("BACKEND_URL =", BACKEND_URL)

# Show status=success/cancel banner if coming back from Stripe
qp = st.query_params
if qp.get("status") == "success":
    st.success("Payment successful! Your subscription is now active.")
elif qp.get("status") == "cancel":
    st.warning("Checkout canceled. No changes were made.")

st.markdown("---")
st.subheader("Step 1 – Enter your email")

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.get("billing_email", ""),
    placeholder="you@example.com",
)

colA, colB = st.columns([1, 2])
with colA:
    check_plan = st.button("Save email & check current plan", use_container_width=True)

status_box = st.empty()

if check_plan:
    if not email.strip():
        status_box.error("Please enter an email.")
    else:
        st.session_state["billing_email"] = email.strip()
        try:
            data = get_subscription_status(email.strip())
            # Expecting: { email, status, plan, price_id }
            status = data.get("status") or "none"
            plan = data.get("plan")  # can be None, basic, pro, enterprise, unknown

            if status in ("active", "trialing"):
                status_box.success(f"Status: {status} • Plan: {plan or 'unknown'}")
            else:
                status_box.info(f"Status: {status} • No active plan found for this email.")
        except Exception as e:
            status_box.error(f"Error contacting backend: {e}")

st.markdown("---")
st.subheader("Step 2 – Compare plans & upgrade")
st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

c1, c2, c3 = st.columns(3)

def plan_card(col, name, price, bullets, plan_key):
    with col:
        st.markdown(f"### {name}")
        st.markdown(f"**{price}**")
        for b in bullets:
            st.markdown(f"- {b}")
        if st.button(f"Choose {name}", key=f"choose_{plan_key}", use_container_width=True):
            if not st.session_state.get("billing_email") and not email.strip():
                st.error("Enter your billing email first (Step 1).")
                return

            chosen_email = (st.session_state.get("billing_email") or email).strip()
            if not chosen_email:
                st.error("Enter your billing email first (Step 1).")
                return

            try:
                checkout_url, raw = create_checkout_session(chosen_email, plan_key)

                if not checkout_url:
                    st.error("Checkout URL was not returned by backend.")
                    st.write("Raw response:", raw)  # shows you exactly what backend returned
                    return

                # ✅ Redirect to Stripe Checkout
                redirect_to(checkout_url)

            except Exception as e:
                st.error(str(e))

plan_card(
    c1,
    "Basic",
    "$9.99 / month",
    [
        "Up to 20 reports / month",
        "Up to 400k characters / month",
        "Executive summaries + key insights",
    ],
    "basic",
)

plan_card(
    c2,
    "Pro",
    "$19.99 / month",
    [
        "Up to 75 reports / month",
        "Up to 1.5M characters / month",
        "Action items, risks, opportunity insights",
    ],
    "pro",
)

plan_card(
    c3,
    "Enterprise",
    "$39.99 / month",
    [
        "Up to 250 reports / month",
        "Up to 5M characters / month",
        "Team accounts, shared templates, & premium support",
    ],
    "enterprise",
)

st.info(
    "Coupon/promo codes appear on the Stripe Checkout page (hosted by Stripe). "
    "If you don't see it, the backend must create the session with allow_promotion_codes=True."
)
