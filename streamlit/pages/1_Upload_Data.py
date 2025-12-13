import os
import streamlit as st
import requests

st.set_page_config(page_title="Upload Data", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set in the Streamlit service.")
    st.stop()

st.title("Upload Data")

with st.sidebar:
    st.header("Navigation")
    try:
        st.page_link("Home.py", label="Home")
    except Exception:
        pass
    st.page_link("pages/Upload_Data.py", label="Upload Data", disabled=True)
    try:
        st.page_link("pages/Billing.py", label="Billing")
    except Exception:
        pass

billing_email = st.text_input(
    "Billing email (used to look up your subscription)",
    value=st.session_state.get("billing_email", ""),
    placeholder="you@example.com",
)

if billing_email.strip():
    st.session_state["billing_email"] = billing_email.strip()

col1, col2 = st.columns([1, 3])
with col1:
    check = st.button("Check subscription plan")

plan = None
status = "none"

if check and billing_email.strip():
    try:
        r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": billing_email.strip()}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            plan = data.get("plan")
            status = data.get("status") or "none"
        else:
            st.error(f"Backend error {r.status_code}: {r.text}")
    except Exception as e:
        st.error(f"Error contacting backend: {e}")

# auto refresh display if email set
if billing_email.strip():
    try:
        r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": billing_email.strip()}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            plan = data.get("plan")
            status = data.get("status") or "none"
    except Exception:
        pass

plan_display = (plan or "None")
st.write(f"**Current plan (for summaries):** {plan_display}")
st.write(f"**Status:** {status}")

st.divider()

uploaded = st.file_uploader("Upload a report file (TXT, MD, PDF, DOCX, CSV).", type=["txt", "md", "pdf", "docx", "csv"])
manual_text = st.text_area("Or paste text manually", height=220)

# Simple extraction: use manual text if present; otherwise just show filename (you can add PDF/docx parsing later)
text_to_summarize = manual_text.strip()
if not text_to_summarize and uploaded is not None:
    # minimal safe fallback so the app doesn't break without parsers
    text_to_summarize = f"Uploaded file: {uploaded.name}\n\n(Parsing not enabled in this file yet. Paste text to summarize.)"

st.subheader("2. Generate a summary")

send_email = st.checkbox("Email this summary to someone", value=True)
recipient_email = st.text_input("Recipient email", value="")

if st.button("Generate Business Summary"):
    if not billing_email.strip():
        st.error("Enter billing email first.")
        st.stop()
    if not text_to_summarize.strip():
        st.error("Upload a file or paste text to summarize.")
        st.stop()
    if send_email and not recipient_email.strip():
        st.error("Enter a recipient email (or uncheck email option).")
        st.stop()

    with st.spinner("Generating summary..."):
        try:
            payload = {
                "billing_email": billing_email.strip(),
                "text": text_to_summarize,
                "recipient_email": recipient_email.strip(),
                "send_email": bool(send_email),
            }
            resp = requests.post(f"{BACKEND_URL}/generate-summary", json=payload, timeout=90)

            if resp.status_code != 200:
                st.error(f"Backend error {resp.status_code}")
                st.code(resp.text)
                st.stop()

            data = resp.json()
            st.success(f"Summary generated for plan: {data.get('plan') or 'basic'}")

            st.markdown("### Summary")
            st.write(data.get("summary", ""))

            if send_email:
                if data.get("emailed"):
                    st.success(f"Email sent to: {recipient_email.strip()}")
                else:
                    st.warning(
                        "Summary generated, but email was NOT sent. "
                        "Check BREVO_API_KEY + EMAIL_FROM in backend env vars and backend logs."
                    )

        except Exception as e:
            st.error(f"Failed to generate summary: {e}")
