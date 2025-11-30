import os
import requests
import streamlit as st

st.set_page_config(page_title="Billing & Plans", page_icon="💳")


# ---------- Backend URL helpers ----------

def get_backend_url() -> str:
    """
    Resolve the backend URL without *requiring* st.secrets.
    Prefer environment variables (Render dashboard), fall back to secrets if present.
    """
    # 1) Try environment variable (recommended on Render)
    url = os.getenv("BACKEND_URL")
    if url:
        return url.rstrip("/")

    # 2) Optional: try Streamlit secrets if they exist
    try:
        # This may raise FileNotFoundError if no secrets.toml exists.
        url = st.secrets["BACKEND_URL"]
        return str(url).rstrip("/")
    except FileNotFoundError:
        return ""  # handled later in the UI
    except KeyError:
        return ""


BACKEND_URL = get_backend_url()


# ---------- Small helpers ----------

def show_backend_missing():
    st.error(
        "The backend URL is not configured. "
        "Set the `BACKEND_URL` environment variable in Render for the Streamlit service."
    )


def create_checkout_session(plan: str, email: str) -> tuple[bool, str]:
    """Call backend /create-checkout-session and return (ok, message_or_url)."""
    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan, "email": email},
            timeout=20,
        )
    except Exception as exc:
        return False, f"Could not reach backend: {exc}"

    if resp.status_code != 200:
        return False, f"Backend returned {resp.status_code}: {resp.text}"

    try:
        data = resp.json()
    except Exception:
        return False, "Backend response was not valid JSON."

    checkout_url = data.get("checkout_url") or data.get("url")
    if not checkout_url:
        return False, "Backend did not return a checkout URL."

    return True, checkout_url


def check_subscription(email: str) -> tuple[bool, str]:
    """Call backend /subscription-status and return (ok, human_message)."""
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=15,
        )
    except Exception as exc:
        return False, f"Could not reach backend while checking subscription: {exc}"

    # 404/204 etc. → treat as "no active subscription"
    if resp.status_code == 404:
        return True, "We didn't find an active subscription for this email yet."
    if resp.status_code != 200:
        return False, f"Backend returned {resp.status_code} while checking subscription."

    try:
        data = resp.json()
    except Exception:
        return False, "Backend subscription response was not valid JSON."

    active = data.get("active", False)
    plan = data.get("plan") or data.get("plan_name") or "a plan"

    if active:
        return True, f"You currently have an active **{plan}** subscription."
    else:
        return True, "We didn't detect an active subscription for this email yet."


# ---------- Read query parameters (Stripe redirect) ----------

query_params = st.query_params  # new API, no experimental_ warning

status = (query_params.get("status") or "").lower()
session_id = query_params.get("session_id") or ""

if status == "success":
    st.success(
        "Checkout complete! To activate your new plan, make sure the **same email** "
        "you used at checkout is saved in Step 1 below."
    )
elif status == "cancelled":
    st.info(
        "You cancelled the checkout. You can choose a plan again below whenever you're ready."
    )

# ---------- Page content ----------

st.title("Billing & Plans")
st.write(
    "Use this page to manage your subscription and upgrade your document summary limits."
)

# ---------- Guard if backend URL is missing ----------

if not BACKEND_URL:
    show_backend_missing()
    st.stop()

# ---------- Step 1 – Add your email ----------

st.subheader("Step 1 – Add your email")

# Pre-fill email from previous session if available
if "saved_email" not in st.session_state:
    st.session_state.saved_email = ""

email = st.text_input(
    "Email address",
    value=st.session_state.saved_email,
    placeholder="you@example.com",
)


col1, col2 = st.columns([1, 2])
with col1:
    if st.button("Save email & check plan", type="primary", use_container_width=True):
        if not email:
            st.warning("Please enter an email address first.")
        else:
            st.session_state.saved_email = email
            ok, message = check_subscription(email)
            if ok:
                st.info(message)
            else:
                st.error(message)
with col2:
    st.caption("We use this email to link your subscription, upload limits, and summaries.")


# ---------- Step 2 – Choose a plan ----------

st.subheader("Step 2 – Choose a plan")

st.caption("Pick the plan that best fits your workload. You can upgrade later as your needs grow.")

col_basic, col_pro, col_ent = st.columns(3)

# --- Basic ---
with col_basic:
    st.markdown("### Basic")
    st.write("$9.99 / month")
    st.write("- Upload up to **5 documents** per month")
    st.write("- Clear AI-generated summaries for clients and stakeholders")
    st.write("- Copy-paste summaries into emails, reports, and slide decks")

    if st.button("Choose Basic", key="btn_basic", use_container_width=True):
        if not email:
            st.warning("Enter your email in Step 1 before choosing a plan.")
        else:
            ok, result = create_checkout_session("basic", email)
            if ok:
                st.session_state.saved_email = email
                st.write("Redirecting to checkout…")
                st.experimental_set_query_params()  # clear local params before leaving
                st.markdown(f'<meta http-equiv="refresh" content="0; url={result}">',
                            unsafe_allow_html=True)
            else:
                st.error(f"Checkout failed: {result}")

# --- Pro ---
with col_pro:
    st.markdown("### Pro")
    st.write("$19.99 / month")
    st.write("- Upload up to **30 documents** per month")
    st.write("- Deeper, more structured summaries (key points, risks, and action items)")
    st.write("- Priority email support")

    if st.button("Choose Pro", key="btn_pro", use_container_width=True):
        if not email:
            st.warning("Enter your email in Step 1 before choosing a plan.")
        else:
            ok, result = create_checkout_session("pro", email)
            if ok:
                st.session_state.saved_email = email
                st.write("Redirecting to checkout…")
                st.experimental_set_query_params()
                st.markdown(f'<meta http-equiv="refresh" content="0; url={result}">',
                            unsafe_allow_html=True)
            else:
                st.error(f"Checkout failed: {result}")

# --- Enterprise ---
with col_ent:
    st.markdown("### Enterprise")
    st.write("$39.99 / month")
    st.write("- **Unlimited uploads** for your team")
    st.write("- Team accounts and shared templates")
    st.write("- Premium support & integration help")

    if st.button("Choose Enterprise", key="btn_ent", use_container_width=True):
        if not email:
            st.warning("Enter your email in Step 1 before choosing a plan.")
        else:
            ok, result = create_checkout_session("enterprise", email)
            if ok:
                st.session_state.saved_email = email
                st.write("Redirecting to checkout…")
                st.experimental_set_query_params()
                st.markdown(f'<meta http-equiv="refresh" content="0; url={result}">',
                            unsafe_allow_html=True)
            else:
                st.error(f"Checkout failed: {result}")


# ---------- Step 3 – Start using your plan ----------

st.subheader("Step 3 – Start using your plan")

st.markdown(
    """
1. Go to the **Upload Data** page (link in the sidebar).
2. Enter the **same email** you used here.
3. Upload a report or paste your content.
4. Click **Generate Business Summary** to create a client-ready summary.
"""
)
