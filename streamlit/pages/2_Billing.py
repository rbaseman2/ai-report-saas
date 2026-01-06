import os
import time
import requests
import streamlit as st
import streamlit.components.v1 as components

# ------------------------------------------------------------
# Billing & Subscription page
# - Checks current plan via backend
# - Creates Stripe Checkout session via backend
# - Auto-redirects to Stripe Checkout (with multiple fallbacks)
# - Shows a clear "next step" after Stripe returns success
# ------------------------------------------------------------

st.set_page_config(page_title="Billing & Subscription", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")


def require_backend() -> None:
    if not BACKEND_URL:
        st.error("BACKEND_URL environment variable is not set.")
        st.stop()


def get_query_params() -> dict:
    # Streamlit query params API differs by version; handle safely.
    try:
        qp = st.query_params
        return dict(qp)
    except Exception:
        return st.experimental_get_query_params()


def normalize_qp_value(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def js_redirect(url: str) -> None:
    # Most reliable in hosted environments: redirect the top frame.
    components.html(
        f"""
        <script>
          window.top.location.href = {url!r};
        </script>
        """,
        height=0,
    )


def meta_refresh(url: str) -> None:
    # Secondary fallback if JS is blocked.
    components.html(
        f"""<meta http-equiv="refresh" content="0; url={url}">""",
        height=0,
    )


def check_subscription(email: str) -> dict:
    r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": email}, timeout=30)
    r.raise_for_status()
    return r.json()


def create_checkout(email: str, plan_key: str) -> dict:
    r = requests.post(
        f"{BACKEND_URL}/create-checkout-session",
        json={"email": email, "plan": plan_key},
        timeout=45,
    )
    r.raise_for_status()
    return r.json()


require_backend()

st.title("Billing & Subscription")

# ------------------------------------------------------------
# Handle Stripe return
# ------------------------------------------------------------
qp = get_query_params()
status = normalize_qp_value(qp.get("status"))
session_id = normalize_qp_value(qp.get("session_id"))

if status == "success":
    st.success("✅ Checkout complete! Your subscription should be active within a few seconds.")
    st.info("Next step: go to **Upload Data** to upload a document and generate a summary.")

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("Continue to Upload Data →", type="primary"):
            try:
                st.switch_page("pages/1_Upload_Data.py")
            except Exception:
                st.write("Use the left sidebar to open **Upload Data**.")
    with c2:
        st.caption("If you don’t see your plan immediately, wait ~10 seconds and click “Check current plan” again.")

    st.divider()

elif status == "cancel":
    st.warning("Checkout was canceled. You can choose a plan again below.")
    st.divider()

# ------------------------------------------------------------
# Step 1: Email + current plan
# ------------------------------------------------------------
st.subheader("Step 1 — Enter your email")

default_email = st.session_state.get("billing_email", "")
billing_email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=default_email,
    key="billing_email_input",
)

status_box = st.empty()

if st.button("Check current plan"):
    email = billing_email.strip()
    if not email:
        st.error("Please enter your email.")
    else:
        st.session_state["billing_email"] = email
        try:
            data = check_subscription(email)
            status_box.success(f"Status: {data.get('status')} | Current plan: {data.get('current_plan')}")
        except Exception as e:
            status_box.error(f"Could not check subscription: {e}")

st.divider()

# ------------------------------------------------------------
# Step 2: Choose plan + checkout
# ------------------------------------------------------------
st.subheader("Step 2 — Compare plans & upgrade")
st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

email = billing_email.strip()
if not email:
    st.warning("Enter your billing email above before selecting a plan.")
    st.stop()

# Persist email so Upload page can reuse if needed.
st.session_state["billing_email"] = email

plans = [
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

msg = st.empty()
redirect_info = st.empty()
fallback_btn = st.empty()


def start_checkout(plan_key: str) -> None:
    msg.info(f"Selected plan: {plan_key}. Creating Stripe Checkout session…")
    try:
        data = create_checkout(email=email, plan_key=plan_key)
        checkout_url = data.get("url")
        if not checkout_url:
            raise RuntimeError(f"Backend did not return checkout URL. Response: {data}")

        # Make fallback visible immediately.
        redirect_info.success("Redirecting to Stripe Checkout… If you are not redirected, use the button below.")
        fallback_btn.link_button("Open Stripe Checkout", checkout_url)

        # Give Streamlit a tick to render, then redirect.
        time.sleep(0.15)

        # Try several redirect methods (some browsers block one but not the other).
        meta_refresh(checkout_url)
        js_redirect(checkout_url)

    except requests.HTTPError as e:
        body = ""
        try:
            body = e.response.text if e.response is not None else ""
        except Exception:
            pass
        msg.error(f"Checkout error: {e} {body}")
    except Exception as e:
        msg.error(f"Checkout error: {e}")


# Render plan cards.
c1, c2, c3 = st.columns(3)
for col, (key, name, price, bullets) in zip([c1, c2, c3], plans):
    with col:
        st.markdown(f"### {name}")
        st.markdown(price)
        for b in bullets:
            st.write(f"• {b}")
        st.button(f"Choose {name}", key=f"choose_{key}", on_click=start_checkout, args=(key,))

st.caption("Coupons/promo codes are entered on the Stripe Checkout page (if enabled in Stripe).")
