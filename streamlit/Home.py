import os
import requests
import streamlit as st

# IMPORTANT: must be first Streamlit command
st.set_page_config(
    page_title="AI Report – Business-Ready Summaries",
    page_icon="📄",
    layout="wide",
)

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")


def get_subscription_status(email: str) -> dict:
    """Ask the backend what plan this email is on."""
    if not BACKEND_URL or not email:
        return {"plan": "free", "active": False}

    try:
        response = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass

    return {"plan": "free", "active": False}


# ---------------------- PAGE LAYOUT ---------------------- #

st.title("AI Report – Turn Long Documents into Client-Ready Summaries")
st.caption(
    "Upload reports, meeting notes, proposals, or research and instantly get clear, "
    "client-friendly summaries you can reuse in emails, slide decks, and internal updates."
)

st.markdown("### How it works")
cols = st.columns(3)

with cols[0]:
    st.subheader("1. Upload")
    st.write(
        "Drag and drop PDFs, Word docs, text files, or CSVs – or paste text directly. "
        "Perfect for meeting notes, research, and long email threads."
    )

with cols[1]:
    st.subheader("2. Summarize")
    st.write(
        "Our AI condenses the content into clear, structured summaries written for "
        "non-technical clients, managers, and stakeholders."
    )

with cols[2]:
    st.subheader("3. Share")
    st.write(
        "Copy the summary into emails, proposals, or presentations. Save time while "
        "still looking thoughtful and professional."
    )

st.divider()

st.subheader("Your account")

email = st.text_input(
    "Email",
    placeholder="you@example.com",
    help="Use the same email you’ll use on the Billing page.",
)

status_col, info_col = st.columns([1, 2])

with status_col:
    if email:
        status = get_subscription_status(email)
        plan = status.get("plan", "free")
        active = status.get("active", False)

        if active:
            st.success(f"Current plan: **{plan.capitalize()}**")
        else:
            st.info("You’re currently on the **Free** tier.")
    else:
        st.info("Enter your email to see your current plan.")

with info_col:
    st.write(
        "Use the **Upload Data** page to generate summaries and the **Billing** page "
        "to upgrade your plan or manage your subscription."
    )

st.markdown(
    """
---

**Tip:** this tool is ideal for:

- Consultants summarizing discovery calls or workshops  
- Solo founders turning research into short updates  
- Small teams sharing insights with non-technical stakeholders  
"""
)
