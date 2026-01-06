import os
import time
import requests
import streamlit as st


# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="Billing & Subscription", page_icon="💳", layout="wide")

DEFAULT_BACKEND = "https://ai-report-backend-ubrx.onrender.com"
BACKEND_URL = os.getenv("BACKEND_URL", DEFAULT_BACKEND).rstrip("/")

SUB_STATUS_ENDPOINT = f"{BACKEND_URL}/subscription-status"
CHECKOUT_ENDPOINT = f"{BACKEND_URL}/create-checkout-session"


# ----------------------------
# Helpers
# ----------------------------
def safe_get_subscription(email: str) -> dict:
    """Return dict with keys: status, plan (or None). Never throws."""
    try:
        r = requests.get(SUB_STATUS_ENDPOINT, params={"email": email}, timeout=20)
        r.raise_for_status()
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return {
            "status": data.get("status", "none"),
            "plan": data.get("plan"),
        }
    except Exception as e:
        return {"status": "error", "plan": None, "error": str(e)}


def safe_create_checkout(email: str, plan: str) -> dict:
    """Return dict with keys: checkout_url/url, session_id. Never throws."""
    try:
        payload = {"email": email, "plan": plan}
        r = requests.post(CHECKOUT_ENDPOINT, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return data
    except requests.HTTPError:
        # capture backend text response too
        try:
            txt = r.text
        except Exception:
            txt = ""
        return {"error": f"HTTP {getattr(r, 'status_code', '??')}: {txt}"}
    except Exception as e:
        return {"error": str(e)}


def plan_card(title, price, bullets, plan_key):
    with st.container(border=True):
        st.subheader(title)
        st.markdown(f"**{price} / month**")
        for b in bullets:
            st.write(f"• {b}")

        disabled = not st.session_state.get("billing_email")
        if st.button(f"Choose {title}", key=f"choose_{plan_key}", disabled=disabled):
            st.session_state["selected_plan"] = plan_key
            st.session_state["checkout_started"] = False
            st.session_state["checkout_url"] = None
            st.session_state["checkout_error"] = None


def js_redirect(url: str):
    # Reliable redirect in Streamlit Cloud/Render
    st.components.v1.html(
        f"""
        <script>
          window.location.href = {repr(url)};
        </script>
        """,
        height=0,
    )


# ----------------------------
# UI
# ----------------------------
st.title("Billing & Subscription")

# Ensure session state keys exist
st.session_state.setdefault("billing_email", "")
st.session_state.setdefault("sub_status", None)
st.session_state.setdefault("selected_plan", None)
st.session_state.setdefault("checkout_url", None)
st.session_state.setdefault("checkout_error", None)
st.session_state.setdefault("checkout_started", False)

st.caption(f"Backend: {BACKEND_URL}")

st.markdown("### Step 1 — Enter your email")

email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state["billing_email"],
    placeholder="you@example.com",
)

col_a, col_b = st.columns([1, 2])

with col_a:
    if st.button("Save email & check current plan"):
        st.session_state["billing_email"] = email.strip()
        if st.session_state["billing_email"]:
            st.session_state["sub_status"] = safe_get_subscription(st.session_state["billing_email"])
        else:
            st.session_state["sub_status"] = {"status": "none", "plan": None}

with col_b:
    status = st.session_state.get("sub_status")
    if status:
        if status.get("status") == "error":
            st.error(f"Could not check subscription: {status.get('error')}")
        else:
            st.success(f"Status: {status.get('status')} | Current plan: {status.get('plan') or 'none'}")

st.divider()

st.markdown("### Step 2 — Compare plans & upgrade")
st.write("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

c1, c2, c3 = st.columns(3)

with c1:
    plan_card(
        "Basic",
        "$9.99",
        [
            "Up to 20 reports / month",
            "Up to 400k characters / month",
            "Executive summaries + key insights",
        ],
        "basic",
    )

with c2:
    plan_card(
        "Pro",
        "$19.99",
        [
            "Up to 75 reports / month",
            "Up to 1.5M characters / month",
            "Action items, risks, and opportunity insights",
        ],
        "pro",
    )

with c3:
    plan_card(
        "Enterprise",
        "$39.99",
        [
            "Up to 250 reports / month",
            "Up to 5M characters / month",
            "Team accounts, shared templates, & premium support",
        ],
        "enterprise",
    )

st.caption("Coupons/promo codes are entered on the Stripe Checkout page (if enabled in Stripe).")

# ----------------------------
# Checkout flow
# ----------------------------
selected = st.session_state.get("selected_plan")
billing_email = st.session_state.get("billing_email")

if selected and billing_email:
    st.info(f"Selected plan: **{selected}**. Creating Stripe Checkout session...")

    # Only create once per click
    if not st.session_state["checkout_started"]:
        st.session_state["checkout_started"] = True
        data = safe_create_checkout(billing_email, selected)

        # Stripe returns either checkout_url or url
        checkout_url = data.get("checkout_url") or data.get("url")
        if checkout_url:
            st.session_state["checkout_url"] = checkout_url
        else:
            st.session_state["checkout_error"] = data.get("error") or str(data)

    if st.session_state.get("checkout_error"):
        st.error(f"Could not start checkout: {st.session_state['checkout_error']}")
    elif st.session_state.get("checkout_url"):
        st.success("Redirecting to Stripe Checkout... If you are not redirected, use the button below.")
        js_redirect(st.session_state["checkout_url"])
        st.link_button("Open Stripe Checkout", st.session_state["checkout_url"])
        st.caption("If your browser blocks redirects, click the button above.")
        time.sleep(0.2)
