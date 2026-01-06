import os
import time
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Billing & Subscription", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

def _require_backend():
    if not BACKEND_URL:
        st.error("BACKEND_URL environment variable is not set.")
        st.stop()

def _get_query_params():
    # Streamlit query params API differs by version; handle safely
    try:
        return st.query_params
    except Exception:
        return st.experimental_get_query_params()

def _set_query_params(**kwargs):
    try:
        st.query_params.update(kwargs)
    except Exception:
        st.experimental_set_query_params(**kwargs)

def _js_redirect(url: str):
    # Most reliable: JS redirect in the top frame
    components.html(
        f"""
        <script>
          window.top.location.href = {url!r};
        </script>
        """,
        height=0,
    )

st.title("Billing & Subscription")

_require_backend()

# ----------------------------
# Handle return from Stripe
# ----------------------------
qp = _get_query_params()
status = (qp.get("status") if isinstance(qp, dict) else None)

# If qp is streamlit QueryParams, values may be strings directly
if isinstance(status, list):
    status = status[0] if status else None

session_id = qp.get("session_id") if isinstance(qp, dict) else None
if isinstance(session_id, list):
    session_id = session_id[0] if session_id else None

if status == "success":
    st.success("✅ Checkout complete! Your subscription should be active within a few seconds.")
    st.info("Next step: go to **Upload Data** to upload a document and generate a summary.")

    colA, colB = st.columns([1, 2])
    with colA:
        if st.button("Continue to Upload Data →", type="primary"):
            try:
                st.switch_page("pages/1_Upload_Data.py")
            except Exception:
                st.write("Open the Upload Data page from the left sidebar.")

    with colB:
        st.caption("If you don’t see your plan immediately, wait ~10 seconds and click “Save email & check current plan” again.")

    st.divider()

elif status == "cancel":
    st.warning("Checkout was canceled. You can choose a plan again below.")
    st.divider()

# ----------------------------
# Step 1: email + current plan
# ----------------------------
st.subheader("Step 1 — Enter your email")

billing_email = st.text_input("Billing email (used to associate your subscription)", key="billing_email")

status_box = st.empty()

def check_subscription(email: str):
    try:
        r = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "current_plan": "unknown", "error": str(e)}

if st.button("Save email & check current plan"):
    if not billing_email.strip():
        st.error("Please enter your email.")
    else:
        data = check_subscription(billing_email.strip())
        if data.get("status") == "error":
            status_box.error(f"Could not check subscription: {data.get('error')}")
        else:
            status_box.success(f"Status: {data.get('status')} | Current plan: {data.get('current_plan')}")

st.divider()

# ----------------------------
# Step 2: Choose plan + checkout
# ----------------------------
st.subheader("Step 2 — Compare plans & upgrade")
st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

if not billing_email.strip():
    st.warning("Enter and save your billing email above before selecting a plan.")
    st.stop()

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

def start_checkout(plan_key: str):
    msg.info(f"Selected plan: {plan_key}. Creating Stripe Checkout session...")

    try:
        r = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"email": billing_email.strip(), "plan": plan_key},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        checkout_url = data.get("url")
        if not checkout_url:
            raise RuntimeError(f"Backend did not return checkout URL. Response: {data}")

        redirect_info.success("Redirecting to Stripe Checkout… If you are not redirected, use the button below.")
        fallback_btn.link_button("Open Stripe Checkout", checkout_url)

        # Give Streamlit a moment to render the fallback button, then redirect
        time.sleep(0.2)
        _js_redirect(checkout_url)

    except requests.HTTPError as e:
        try:
            body = r.text
        except Exception:
            body = ""
        msg.error(f"Checkout error: {e} {body}")
    except Exception as e:
        msg.error(f"Checkout error: {e}")

# Plan cards
c1, c2, c3 = st.columns(3)
for col, (key, name, price, bullets) in zip([c1, c2, c3], plans):
    with col:
        st.markdown(f"### {name}")
        st.markdown(price)
        for b in bullets:
            st.write(f"• {b}")
        st.button(f"Choose {name}", key=f"choose_{key}", on_click=start_checkout, args=(key,))

st.caption("Coupons/promo codes are entered on the Stripe Checkout page (if enabled in Stripe).")
