import os
import time
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Billing & Subscription", layout="wide")

# ------------------------------------------------------------
# Billing & Subscription
# - Checks current plan via backend (/subscription-status)
# - Creates Stripe Checkout session via backend (/create-checkout-session)
# - Auto-redirects to Stripe Checkout (JS + meta refresh fallback)
# - After successful checkout, shows a single clear next step to Upload Data
# ------------------------------------------------------------

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
UPLOAD_PAGE_PATH = "/Upload_Data"   # Streamlit page route (matches your navigation item)

def _require_backend():
    if not BACKEND_URL:
        st.error("BACKEND_URL environment variable is not set.")
        st.stop()

def _get_query_params():
    # Streamlit has changed query param APIs over versions; support both.
    try:
        # Streamlit >= 1.30
        qp = st.query_params
        return dict(qp)
    except Exception:
        try:
            return st.experimental_get_query_params()  # older Streamlit
        except Exception:
            return {}

def _set_query_params(**kwargs):
    # Best effort: clear/replace query params to avoid repeated "success" handling.
    try:
        st.query_params.clear()
        for k, v in kwargs.items():
            st.query_params[k] = v
    except Exception:
        try:
            st.experimental_set_query_params(**kwargs)
        except Exception:
            pass

def _redirect(url: str):
    """Attempt immediate browser redirect, with fallbacks."""
    safe_url = url.replace('"', "%22")
    components.html(
        f"""
        <meta http-equiv="refresh" content="0; url={safe_url}">
        <script>
          try {{
            window.location.href = "{safe_url}";
            window.location.replace("{safe_url}");
          }} catch(e) {{}}
        </script>
        <p>Redirecting to Stripe Checkout… If you are not redirected, use the button below.</p>
        """,
        height=70,
    )

def _call_subscription_status(email: str):
    r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": email}, timeout=30)
    # If backend returns non-JSON on error, raise cleanly
    r.raise_for_status()
    return r.json()

def _call_create_checkout_session(email: str, plan: str):
    r = requests.post(
        f"{BACKEND_URL}/create-checkout-session",
        json={"email": email, "plan": plan},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    # Support both keys depending on backend version
    url = data.get("url") or data.get("checkout_url") or data.get("checkoutUrl")
    if not url:
        raise RuntimeError(f"Backend did not return checkout URL. Response keys: {list(data.keys())}")
    return url

# -----------------------------
# UI
# -----------------------------
st.title("Billing & Subscription")
_require_backend()

# Keep email in session to avoid retyping after checkout
if "billing_email" not in st.session_state:
    st.session_state["billing_email"] = ""

# -----------------------------
# Handle return from Stripe
# -----------------------------
qp = _get_query_params()
status = (qp.get("status") or [None])[0] if isinstance(qp.get("status"), list) else qp.get("status")

# Common pattern: you return to /Billing?status=success&session_id=...
if status == "success":
    # On success, show a single clear instruction and short summary
    email = st.session_state.get("billing_email", "")
    plan = st.session_state.get("selected_plan", "")
    st.success("Payment successful. Your subscription is active.")
    if plan:
        st.info(f"Subscribed plan: **{plan}**")
    if email:
        st.caption(f"Account email: {email}")

    # Big next-step CTA
    st.markdown("### Next step")
    st.markdown("Go to **Upload Data** to upload a document and generate your summary.")
    if st.button("Go to Upload Data", type="primary"):
        st.switch_page(f"pages/1_Upload_Data.py") if hasattr(st, "switch_page") else st.write("Navigate to Upload Data from the left menu.")

    # Prevent re-processing success on refresh
    _set_query_params()
    st.stop()

elif status == "cancel":
    st.warning("Checkout was cancelled. You can choose a plan again below.")
    _set_query_params()

# -----------------------------
# Step 1: Email + Current plan
# -----------------------------
st.subheader("Step 1 — Enter your email")
email = st.text_input(
    "Billing email (used to associate your subscription)",
    value=st.session_state["billing_email"],
    placeholder="you@example.com",
)
st.session_state["billing_email"] = email.strip()

col_a, col_b = st.columns([1, 3])
with col_a:
    check = st.button("Check current plan")
with col_b:
    status_box = st.empty()

if check:
    if not st.session_state["billing_email"]:
        status_box.error("Please enter your email first.")
    else:
        try:
            info = _call_subscription_status(st.session_state["billing_email"])
            # Expected backend shape: {"status":"active|none|trialing|canceled", "plan":"basic|pro|enterprise"}
            sub_status = info.get("status", "unknown")
            plan = info.get("plan", "none")
            st.session_state["current_plan"] = plan
            if sub_status == "active":
                status_box.success(f"Status: {sub_status} | Current plan: {plan}")
            else:
                status_box.info(f"Status: {sub_status} | Current plan: {plan}")
        except requests.HTTPError as e:
            # show backend JSON error if any
            try:
                status_box.error(f"Could not check subscription. {e.response.json()}")
            except Exception:
                status_box.error(f"Could not check subscription. {e}")
        except Exception as e:
            status_box.error(f"Could not check subscription. {e}")

st.divider()

# -----------------------------
# Step 2: Choose plan + Checkout
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

selected = st.session_state.get("selected_plan", "")
checkout_url = st.session_state.get("checkout_url", "")

for i, (code, name, price, bullets) in enumerate(plans):
    with cols[i]:
        st.markdown(f"### {name}")
        st.markdown(price)
        for b in bullets:
            st.markdown(f"- {b}")
        btn = st.button(f"Choose {name}", key=f"choose_{code}", use_container_width=True)
        if btn:
            if not st.session_state["billing_email"]:
                st.error("Please enter your email above first.")
                st.stop()

            st.session_state["selected_plan"] = code
            st.info(f"Selected plan: {code}. Creating Stripe Checkout session…")

            try:
                url = _call_create_checkout_session(st.session_state["billing_email"], code)
                st.session_state["checkout_url"] = url
                # Attempt auto-redirect
                _redirect(url)
                # Small pause so the browser has time to execute redirect JS
                time.sleep(0.25)
            except requests.HTTPError as e:
                try:
                    st.error(e.response.json())
                except Exception:
                    st.error(str(e))
            except Exception as e:
                st.error(f"Could not create checkout session: {e}")

# If redirect is blocked by the browser, show a manual button as fallback
if st.session_state.get("checkout_url"):
    st.markdown("")
    st.caption("If your browser blocks redirects, click below:")
    if st.button("Open Stripe Checkout", type="secondary"):
        st.markdown(f"[Open Checkout]({st.session_state['checkout_url']})")
