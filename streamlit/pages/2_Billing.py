import os
import requests
import streamlit as st

st.set_page_config(
    page_title="Billing & Plans – AI Report",
    page_icon="💳",
    layout="centered",
)

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

st.title("Billing & Plans")
st.caption("Choose a plan and manage your subscription.")

st.subheader("Your email")
st.caption("We use this email to link your subscription, upload limits, and summaries.")
email = st.text_input("Email address", placeholder="you@example.com")

st.markdown("---")

if not email:
    st.info("Enter your email first, then choose a plan.")
    st.stop()


def create_checkout_session(plan: str) -> dict:
    """Ask backend to create a Stripe Checkout Session."""
    if not BACKEND_URL:
        return {"error": "BACKEND_URL is not configured."}

    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={
                "email": email,
                "plan": plan,  # 'basic', 'pro', 'enterprise'
            },
            timeout=30,
        )
    except Exception as exc:
        return {"error": f"Network error: {exc}"}

    if resp.status_code != 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        msg = data.get("detail") or f"Backend error ({resp.status_code})"
        return {"error": msg}

    return resp.json()


cols = st.columns(3)

# -------- BASIC ---------- #
with cols[0]:
    st.subheader("Basic")
    st.write("**$9.99 / month**")
    st.markdown(
        """
- Upload up to **5 documents per month**
- Clear AI-generated summaries for clients and stakeholders
- Copy-paste summaries into emails, reports, and slide decks
"""
    )
    if st.button("Choose Basic"):
        result = create_checkout_session("basic")
        if "error" in result:
            st.error(f"Checkout failed: {result['error']}")
        else:
            checkout_url = result.get("checkout_url")
            if checkout_url:
                st.success("Redirecting you to secure checkout…")
                st.markdown(f"[Click here to complete checkout]({checkout_url})")
            else:
                st.error("Backend did not return a checkout URL.")

# -------- PRO ---------- #
with cols[1]:
    st.subheader("Pro")
    st.write("**$19.99 / month**")
    st.markdown(
        """
- Upload up to **30 documents per month**
- Deeper, more structured summaries (key points, risks, and action items)
- Priority email support
"""
    )
    if st.button("Choose Pro"):
        result = create_checkout_session("pro")
        if "error" in result:
            st.error(f"Checkout failed: {result['error']}")
        else:
            checkout_url = result.get("checkout_url")
            if checkout_url:
                st.success("Redirecting you to secure checkout…")
                st.markdown(f"[Click here to complete checkout]({checkout_url})")
            else:
                st.error("Backend did not return a checkout URL.")

# -------- ENTERPRISE ---------- #
with cols[2]:
    st.subheader("Enterprise")
    st.write("**$39.99 / month**")
    st.markdown(
        """
- **Unlimited uploads** for your team
- Team accounts and shared templates
- Premium support & integration help
"""
    )
    if st.button("Choose Enterprise"):
        result = create_checkout_session("enterprise")
        if "error" in result:
            st.error(f"Checkout failed: {result['error']}")
        else:
            checkout_url = result.get("checkout_url")
            if checkout_url:
                st.success("Redirecting you to secure checkout…")
                st.markdown(f"[Click here to complete checkout]({checkout_url})")
            else:
                st.error("Backend did not return a checkout URL.")

st.markdown(
    """
---

After a successful checkout, your plan will be updated automatically and your upload
limits will adjust on the **Upload Data** page.
"""
)
