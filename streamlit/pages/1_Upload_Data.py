import os
import streamlit as st
import requests

st.set_page_config(page_title="Upload Data", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set.")
    st.stop()

st.title("Upload Data")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Navigation")

    try:
        st.page_link("Home.py", label="Home")
    except Exception:
        st.write("Home")

    st.page_link("pages/1_Upload_Data.py", label="Upload Data", disabled=True)
    st.page_link("pages/2_Billing.py", label="Billing")

# ---------------- Helpers ----------------
def fetch_subscription(email: str):
    r = requests.get(
        f"{BACKEND_URL}/subscription-status",
        params={"email": email},
        timeout=20
    )
    r.raise_for_status()
    return r.json()

# ---------------- Billing Email ----------------
billing_email = st.text_input(
    "Billing email (used to look up your subscription)",
    value=st.session_state.get("billing_email", "")
)

if st.button("Check subscription plan"):
    st.session_state["billing_email"] = billing_email.strip()

plan = None
status = "none"

if st.session_state.get("billing_email"):
    try:
        sub = fetch_subscription(st.session_state["billing_email"])
        plan = sub.get("plan") or "basic"
        status = sub.get("status") or "none"
    except Exception as e:
        st.error(f"Backend error: {e}")

st.markdown(f"**Current plan (for summaries):** {plan.title()}")
st.markdown(f"**Status:** {status}")

st.divider()

# ---------------- Upload ----------------
uploaded = st.file_uploader(
    "Upload a report (TXT, MD, PDF, DOCX, CSV)",
    type=["txt", "md", "pdf", "docx", "csv"]
)

manual_text = st.text_area("Or paste text manually", height=200)

# ---------------- Generate Summary ----------------
st.subheader("2. Generate a summary")

send_email = st.checkbox("Email this summary to someone", value=True)
recipient_email = st.text_input("Recipient email")

if st.button("Generate Business Summary"):
    if not st.session_state.get("billing_email"):
        st.error("Check your subscription first.")
        st.stop()

    if not uploaded and not manual_text.strip():
        st.error("Upload a file or paste text.")
        st.stop()

    payload = {
        "billing_email": st.session_state["billing_email"],
        "recipient_email": recipient_email if send_email else None,
        "send_email": send_email,
        "text": manual_text.strip()
    }

    files = None
    if uploaded:
        files = {"file": (uploaded.name, uploaded.getvalue())}

    with st.spinner("Generating summary..."):
        r = requests.post(
            f"{BACKEND_URL}/generate-summary",
            data=payload,
            files=files,
            timeout=120
        )

    if r.status_code != 200:
        st.error(f"Backend error {r.status_code}")
        st.code(r.text)
        st.stop()

    data = r.json()
    st.success("Summary generated")
    st.markdown("### Summary")
    st.write(data["summary"])

    if send_email:
        if data.get("emailed"):
            st.success("Email sent successfully")
        else:
            st.warning("Summary generated, but email was not sent")
