import os
import time

import requests
import streamlit as st
import streamlit.components.v1 as components

# -----------------------------
# Config
# -----------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")

PLANS = {
    "basic": {
        "label": "Basic",
        "price": "$9.99 / month",
        "bullets": [
            "Up to 20 reports / month",
            "Up to 400k characters / month",
            "Executive summaries + key insights",
        ],
    },
    "pro": {
        "label": "Pro",
        "price": "$19.99 / month",
        "bullets": [
            "Up to 75 reports / month",
            "Up to 1.5M characters / month",
            "Action items, risks, and opportunity insights",
        ],
    },
    "enterprise": {
        "label": "Enterprise",
        "price": "$39.99 / month",
        "bullets": [
            "Up to 250 reports / month",
            "Up to 5M characters / month",
            "Team accounts, shared templates, & premium support",
        ],
    },
}

# -----------------------------
# Helpers
# -----------------------------

def _get_query_params() -> dict:
    """Works across Streamlit versions."""
    try:
        # Streamlit >= 1.30
        return dict(st.query_params)
    except Exception:
        return st.experimental_get_query_params()


def _clear_query_params():
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()


def _backend_get(path: str, params: dict | None = None, timeout: int = 25):
    url = f"{BACKEND_URL}{path}"
    return requests.get(url, params=params, timeout=timeout)


def _backend_post(path: str, payload: dict, timeout: int = 45):
    url = f"{BACKEND_URL}{path}"
    return requests.post(url, json=payload, timeout=timeout)


def _render_redirect(checkout_url: str):
    """Attempt redirect in multiple ways.

    Note: some hosting providers / browsers block programmatic redirects.
    We always show a fallback button.
    """

    # 1) meta refresh (sometimes works even when JS is blocked)
    st.markdown(
        f"""
<meta http-equiv="refresh" content="0; url={checkout_url}">
""",
        unsafe_allow_html=True,
    )

    # 2) JS redirect (runs inside component iframe; may be blocked by sandbox)
    components.html(
        f"""
<script>
(function() {{
  var u = {checkout_url!r};
  try {{
    // try top-level navigation first
    window.top.location.href = u;
    return;
  }} catch (e) {{}}
  try {{
    window.location.href = u;
    return;
  }} catch (e) {{}}
  try {{
    var a = document.createElement('a');
    a.href = u;
    a.target = '_top';
    document.body.appendChild(a);
    a.click();
  }} catch (e) {{}}
}})();
</script>
""",
        height=0,
    )

    st.success("Redirecting to Stripe Checkout… If you are not redirected, use the button below.")
    st.link_button("Open Stripe Checkout", checkout_url, type="primary")


# -----------------------------
# Page
# -----------------------------

st.set_page_config(page_title="Billing & Subscription", layout="wide")

st.title("Billing & Subscription")

# ------------------------------------------------------------
# Post-checkout UX
# Stripe returns users here with ?status=success|cancel
# Give a clear next step to proceed to Upload Data.
# ------------------------------------------------------------
try:
    _qp = dict(st.query_params)  # Streamlit >= 1.30
except Exception:
    _qp = st.experimental_get_query_params()

_status = (_qp.get("status", [""])[0] if isinstance(_qp.get("status"), list) else _qp.get("status", ""))

if _status == "success":
    st.success("Checkout complete. Next step: upload your document to generate your summary.")
    # Streamlit's built-in page switcher (falls back to link if unavailable)
    col_a, col_b = st.columns([1, 3])
    with col_a:
        try:
            if st.button("Go to Upload Data", type="primary"):
                st.switch_page("pages/1_Upload_Data.py")
        except Exception:
            st.markdown("➡️ **Next:** Use the left menu and click **Upload Data**.")
    st.divider()
elif _status == "cancel":
    st.warning("Checkout was canceled. You can select a plan again below.")
    st.divider()

# Preserve email across pages
if "billing_email" not in st.session_state:
    st.session_state["billing_email"] = ""

# ---- Step 1: Email + plan status ----
st.subheader("Step 1 — Enter your email")

billing_email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state["billing_email"],
    placeholder="you@example.com",
)

if billing_email:
    st.session_state["billing_email"] = billing_email.strip()

status_box = st.empty()

if st.button("Check current plan"):
    if not st.session_state["billing_email"]:
        st.error("Please enter your billing email first.")
    else:
        try:
            r = _backend_get("/subscription-status", params={"email": st.session_state["billing_email"]})
            if r.status_code == 200:
                data = r.json()
                sub_status = data.get("status", "none")
                plan = data.get("plan", "none")
                status_box.success(f"Status: {sub_status} | Current plan: {plan}")
            else:
                status_box.error(f"Could not check subscription. {r.text}")
        except Exception as e:
            status_box.error(f"Could not check subscription. {e}")

st.divider()

# ---- Step 2: Choose plan -> create checkout session ----
st.subheader("Step 2 — Compare plans & upgrade")
st.caption("Coupons/promo codes are entered on the Stripe Checkout page (if enabled in Stripe).")

cols = st.columns(3)
plan_keys = ["basic", "pro", "enterprise"]

for idx, plan_key in enumerate(plan_keys):
    plan = PLANS[plan_key]
    with cols[idx]:
        st.markdown(f"### {plan['label']}")
        st.markdown(plan["price"])
        for b in plan["bullets"]:
            st.markdown(f"• {b}")

        if st.button(f"Choose {plan['label']}", key=f"choose_{plan_key}"):
            if not st.session_state.get("billing_email"):
                st.error("Enter your billing email above first.")
                st.stop()

            st.info(f"Selected plan: {plan_key}. Creating Stripe Checkout session…")
            try:
                resp = _backend_post(
                    "/create-checkout-session",
                    {"email": st.session_state["billing_email"], "plan": plan_key},
                )

                if resp.status_code != 200:
                    st.error(f"Checkout session failed: {resp.text}")
                    st.stop()

                payload = resp.json()
                checkout_url = payload.get("url") or payload.get("checkout_url")

                if not checkout_url:
                    st.error(f"Backend did not return a checkout URL. Response: {payload}")
                    st.stop()

                # Small delay improves reliability on some hosts
                time.sleep(0.2)
                _render_redirect(checkout_url)

            except requests.RequestException as e:
                st.error(f"Network error calling backend: {e}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")

