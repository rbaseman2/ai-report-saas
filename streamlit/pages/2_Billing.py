import os
import requests
import streamlit as st

# Must be first Streamlit call
st.set_page_config(
    page_title="Billing & Plans – AI Report",
    page_icon="💳",
    layout="wide",
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

st.title("Billing & Plans")

st.caption(
    "Use this page to manage your subscription and upgrade your document summary limits."
)

# ---------- Query params (e.g. after redirect back from Stripe) ----------

params = st.query_params
status = params.get("status")
if status == "success":
    st.success("Your subscription was completed successfully.")
elif status == "cancelled":
    st.info("Checkout cancelled. You can start again at any time.")
elif status == "error":
    st.error("There was a problem with checkout. Please try again or contact support.")

st.markdown("---")

# ---------- Email capture ----------

st.markdown("### Your email")
st.caption(
    "We use this email to link your subscription, upload limits, and summaries. "
    "Use the same one you enter on the Stripe checkout page."
)

default_email = st.session_state.get("user_email", "")
email = st.text_input("Email address", value=default_email or "", key="billing_email")

if st.button("Save email"):
    if not email:
        st.warning("Please enter an email address first.")
    else:
        st.session_state["user_email"] = email
        st.success("Email saved. You can now choose a plan below to continue to checkout.")

st.markdown("---")

# ---------- Plan cards ----------

st.markdown("### Plans")

col_basic, col_pro, col_ent = st.columns(3)


def start_checkout(plan: str):
    """Call backend to create a Stripe Checkout Session and give the user the link."""
    if not email:
        st.warning("Please enter and save your email before choosing a plan.")
        return

    try:
        payload = {"email": email, "plan": plan}
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        checkout_url = data.get("checkout_url")
        if not checkout_url:
            st.error("Backend did not return a checkout URL.")
            return

        st.success("Checkout created. Click the button below to continue securely on Stripe.")
        st.markdown(
            f"[➡️ Open secure checkout]({checkout_url})",
            unsafe_allow_html=False,
        )
    except Exception as exc:
        st.error(f"Checkout failed: {exc}")


with col_basic:
    st.subheader("Basic")
    st.caption("$9.99 / month")
    st.markdown(
        """
- Upload up to **5 documents per month**  
- Clear AI-generated summaries for clients and stakeholders  
- Copy-paste summaries into emails, reports, and slide decks  
        """
    )
    if st.button("Choose Basic"):
        start_checkout("basic")

with col_pro:
    st.subheader("Pro")
    st.caption("$19.99 / month")
    st.markdown(
        """
- Upload up to **30 documents per month**  
- Deeper, more structured summaries (key points, risks, and action items)  
- Priority email support  
        """
    )
    if st.button("Choose Pro"):
        start_checkout("pro")

with col_ent:
    st.subheader("Enterprise")
    st.caption("$39.99 / month")
    st.markdown(
        """
- **Unlimited uploads** for your team  
- Team accounts and shared templates  
- Premium support & integration help  
        """
    )
    if st.button("Choose Enterprise"):
        start_checkout("enterprise")

st.markdown("---")

st.caption(
    "After a successful checkout, your plan will be updated automatically and your upload "
    "limits will adjust on the **Upload Data** page (once enforced in the backend)."
)
