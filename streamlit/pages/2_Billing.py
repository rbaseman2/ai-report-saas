# pages/2_Billing.py

import requests
import streamlit as st

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------

st.set_page_config(page_title="Billing & Plans – AI Report", page_icon="💳")

# Backend URL (FastAPI)
# Prefer st.secrets if set, otherwise fall back to your Render backend URL.
BACKEND_URL = st.secrets.get(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",
)

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def get_qp_value(name: str, default: str = "") -> str:
    """Streamlit 1.40+ query param helper."""
    qp = st.query_params
    if name not in qp:
        return default
    value = qp[name]
    if isinstance(value, list):
        return value[0] if value else default
    return value or default


def update_query_params(email: str | None = None, plan: str | None = None):
    params = {}
    if email:
        params["email"] = email
    if plan:
        params["plan"] = plan
    st.query_params = params


def start_checkout(plan: str, email: str):
    """Call the backend to create a Stripe Checkout session."""
    if not email:
        st.error("Please enter your email above before choosing a plan.")
        return

    payload = {"plan": plan, "email": email}

    with st.spinner("Contacting payment provider…"):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/create-checkout-session",
                json=payload,
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            st.error(f"Could not reach the backend: {e}")
            return

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text
        st.error(f"Checkout failed: {resp.status_code} – {detail}")
        return

    data = resp.json()
    checkout_url = data.get("checkout_url")
    if not checkout_url:
        st.error("Backend did not return a checkout URL.")
        return

    # Store for this session so the user can come back if needed
    st.session_state["last_checkout_url"] = checkout_url

    st.success("Almost done – open the secure Stripe checkout in a new tab:")
    st.markdown(f"[🔒 Open secure checkout]({checkout_url})")


# ---------------------------------------------------------------------
# Page content
# ---------------------------------------------------------------------

st.title("Billing & Plans")

st.caption(
    "Use this page to choose a plan and manage your upload limits. "
    "After checkout, you can start generating richer business summaries."
)

st.write(f"Using backend: `{BACKEND_URL}`")

st.divider()

# --- Email section ---------------------------------------------------

st.subheader("Your email")

# Read from URL or session
email_from_url = get_qp_value("email", "")
if "billing_email" not in st.session_state:
    st.session_state["billing_email"] = email_from_url

email = st.text_input(
    "Email address",
    value=st.session_state.get("billing_email", ""),
    placeholder="you@example.com",
    help="We use this only to link your subscription and summaries.",
)

col_email_btn, _ = st.columns([1, 3])
with col_email_btn:
    if st.button("Save email"):
        st.session_state["billing_email"] = email.strip()
        update_query_params(email=email.strip(), plan=get_qp_value("plan", ""))
        if email.strip():
            st.success("Email saved. Next, choose a plan below.")
        else:
            st.warning("Email cleared. Please enter an email before checking out.")

st.divider()

# --- Plans section ---------------------------------------------------

st.subheader("Plans")

current_plan = get_qp_value("plan", "")

if current_plan:
    st.info(
        f"Checkout complete for **{current_plan.capitalize()}** plan (or in progress). "
        "You can now go to the **Upload Data** page and start using your plan."
    )

col_basic, col_pro, col_ent = st.columns(3)

with col_basic:
    st.markdown("### Basic")
    st.markdown("**$9.99 / month**")
    st.markdown(
        """
- Upload up to **5 documents per month**
- Clear AI-generated summaries for clients and stakeholders
- Copy-paste summaries into emails, reports, and slide decks
        """
    )
    if st.button("Choose Basic"):
        start_checkout("basic", email.strip())

with col_pro:
    st.markdown("### Pro")
    st.markdown("**$19.99 / month**")
    st.markdown(
        """
- Upload up to **30 documents per month**
- Deeper, more structured summaries (key points, risks, and action items)
- Priority email support
        """
    )
    if st.button("Choose Pro"):
        start_checkout("pro", email.strip())

with col_ent:
    st.markdown("### Enterprise")
    st.markdown("**$39.99 / month**")
    st.markdown(
        """
- **Unlimited uploads** for your team
- Team accounts and shared templates
- Premium support & integration help
        """
    )
    if st.button("Choose Enterprise"):
        start_checkout("enterprise", email.strip())

st.divider()

# --- Step 3 instructions --------------------------------------------

st.subheader("Step 3 – Start using your plan")

st.markdown(
    """
1. Go to the **Upload Data** page (link on the left).
2. Use the **same email** you entered on this Billing page.
3. Upload a report or paste your content.
4. Click **Generate Business Summary** to create a client-ready summary.
"""
)

st.markdown("[Open Upload Data →](/Upload_Data)")
