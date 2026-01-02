import os

import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Billing & Subscription", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set.")
    st.stop()


# -----------------------------------------------------------------------------
# Backend helpers
# -----------------------------------------------------------------------------

def get_subscription_status(email: str) -> dict:
    """Call GET /subscription-status. Returns dict with keys like status/current_plan."""
    resp = requests.get(
        f"{BACKEND_URL}/subscription-status",
        params={"email": email},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def create_checkout_session(email: str, plan: str) -> dict:
    """Call POST /create-checkout-session. Returns dict with checkout_url/url/session_id."""
    resp = requests.post(
        f"{BACKEND_URL}/create-checkout-session",
        json={"email": email, "plan": plan},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def redirect_to_checkout(url: str):
    """Redirect the browser to Stripe Checkout.

    Streamlit apps can run inside an iframe (esp. on hosted platforms).
    window.top.location works more reliably than window.location.
    """
    st.success("Redirecting to Stripe Checkout… If you are not redirected, use the button below.")

    # reliable auto-redirect
    html = f"""
    <script>
      try {{
        window.top.location.href = {url!r};
      }} catch (e) {{
        window.location.href = {url!r};
      }}
    </script>
    """
    components.html(html, height=0)

    # fallback button (always visible)
    st.link_button("Open Stripe Checkout", url)


# -----------------------------------------------------------------------------
# State
# -----------------------------------------------------------------------------

if "billing_email" not in st.session_state:
    st.session_state.billing_email = ""
if "selected_plan" not in st.session_state:
    st.session_state.selected_plan = None


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------

st.title("Billing & Subscription")

st.subheader("Step 1 — Enter your email")
email_input = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state.billing_email,
    placeholder="you@example.com",
)

col_a, col_b = st.columns([1, 5])
with col_a:
    check_btn = st.button("Save email & check current plan")

if check_btn:
    st.session_state.billing_email = email_input.strip()
    if not st.session_state.billing_email:
        st.warning("Please enter an email address.")
    else:
        try:
            status = get_subscription_status(st.session_state.billing_email)
            st.info(
                f"Status: {status.get('status', 'unknown')} | Current plan: {status.get('current_plan', 'unknown')}"
            )
        except requests.HTTPError as e:
            st.error(f"Could not check subscription. {e}")
        except requests.RequestException as e:
            st.error(f"Could not reach backend. {e}")

st.divider()

st.subheader("Step 2 — Compare plans & upgrade")

plans = [
    {
        "title": "Basic",
        "price": "$9.99 / month",
        "features": [
            "Up to 20 reports / month",
            "Up to 400k characters / month",
            "Executive summaries + key insights",
        ],
        "key": "basic",
    },
    {
        "title": "Pro",
        "price": "$19.99 / month",
        "features": [
            "Up to 75 reports / month",
            "Up to 1.5M characters / month",
            "Action items, risks, and opportunity insights",
        ],
        "key": "pro",
    },
    {
        "title": "Enterprise",
        "price": "$39.99 / month",
        "features": [
            "Up to 250 reports / month",
            "Up to 5M characters / month",
            "Team accounts, shared templates, & premium support",
        ],
        "key": "enterprise",
    },
]

st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

c1, c2, c3 = st.columns(3)


def render_plan_card(col, plan):
    with col:
        st.markdown(f"### {plan['title']}")
        st.markdown(f"**{plan['price']}**")
        for f in plan["features"]:
            st.markdown(f"• {f}")

        clicked = st.button(f"Choose {plan['title']}", key=f"choose_{plan['key']}")
        if clicked:
            st.session_state.selected_plan = plan["key"]

            if not st.session_state.billing_email:
                st.warning("Enter and save your billing email above before selecting a plan.")
                return

            try:
                data = create_checkout_session(st.session_state.billing_email, plan["key"])
                checkout_url = data.get("checkout_url") or data.get("url")
                if not checkout_url:
                    st.error(f"Checkout URL was not returned by backend. Response keys: {list(data.keys())}")
                    return
                redirect_to_checkout(checkout_url)

            except requests.HTTPError as e:
                st.error(f"Backend returned an error when creating checkout: {e}")
            except requests.RequestException as e:
                st.error(f"Could not reach backend to start checkout: {e}")


render_plan_card(c1, plans[0])
render_plan_card(c2, plans[1])
render_plan_card(c3, plans[2])

st.caption(
    "Coupons/promo codes are entered on the Stripe Checkout page (they will appear if enabled in your Stripe settings)."
)
