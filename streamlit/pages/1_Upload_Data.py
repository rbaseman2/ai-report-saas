# streamlit/pages/1_Upload_Data.py

import io
import os
import requests
import streamlit as st
from PyPDF2 import PdfReader  # ensure this is in requirements.txt

st.set_page_config(page_title="Upload Data – AI Report", page_icon="📄")

# Get backend URL from environment variable
BACKEND_URL = os.getenv("BACKEND_URL")

# --- Sidebar navigation (only existing pages) ---
st.sidebar.title("Navigation")
st.sidebar.page_link("Home.py", label="Home")
st.sidebar.page_link("pages/1_Upload_Data.py", label="Upload Data", disabled=True)
st.sidebar.page_link("pages/2_Billing.py", label="Billing")

st.title("Upload Data")

if not BACKEND_URL:
    st.error(
        "BACKEND_URL environment variable is not set for the frontend service.\n\n"
        "Go to the **Render dashboard → your Streamlit (frontend) service → Environment** "
        "and add `BACKEND_URL` pointing to your backend "
        "(e.g. `https://ai-report-backend-xxxx.onrender.com`)."
    )
    st.stop()

billing_email = st.text_input(
    "Billing email (used to look up your subscription)",
    value=st.session_state.get("billing_email", ""),
)

if st.button("Check subscription plan"):
    if not billing_email:
        st.warning("Please enter your billing email first.")
    else:
        st.session_state["billing_email"] = billing_email
        try:
            resp = requests.get(
                f"{BACKEND_URL.rstrip('/')}/subscription-status",
                params={"email": billing_email},
                timeout=20,
            )
            if resp.status_code != 200:
                st.error(f"Backend error: {resp.status_code} - {resp.text}")
            else:
                data = resp.json()
                plan = data.get("plan") or "basic"
                st.session_state["current_plan"] = plan
                status = data.get("status", "none")
                st.success(
                    f"Subscription status: {status}. Plan: {plan.capitalize() if plan else 'None'}"
                )
        except Exception as e:
            st.error(f"Error contacting backend: {e}")

current_plan = st.session_state.get("current_plan", "basic")
st.markdown(f"**Current plan (for summaries):** `{current_plan.capitalize()}`")

st.markdown("---")
st.subheader("Upload a report file")

uploaded_file = st.file_uploader(
    "Upload a TXT, MD, PDF, DOCX, or CSV file", type=["txt", "md", "pdf", "docx", "csv"]
)

manual_text = st.text_area("Or paste text manually", height=200)

# ------------------------------------------------------------------
# Extract text from uploaded file
# ------------------------------------------------------------------
def extract_text_from_upload(file) -> str:
    if file is None:
        return ""
    name = file.name.lower()

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(file.read()))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages)

    # For simplicity, treat other types as raw text
    return file.read().decode(errors="ignore")


report_text = ""

if uploaded_file is not None:
    report_text = extract_text_from_upload(uploaded_file)
elif manual_text.strip():
    report_text = manual_text.strip()

st.markdown("---")
st.subheader("2. Generate a summary")

email_checkbox = st.checkbox("Email this summary to someone")
recipient_email = None
if email_checkbox:
    recipient_email = st.text_input("Recipient email", key="recipient_email")

if st.button("Generate Business Summary"):
    if not report_text.strip():
        st.warning("Please upload a file or paste text to summarize.")
    else:
        with st.spinner("Generating summary..."):
            try:
                payload = {
                    "text": report_text,
                    "plan": current_plan or "basic",
                    "recipient_email": recipient_email or None,
                }
                resp = requests.post(
                    f"{BACKEND_URL.rstrip('/')}/summarize", json=payload, timeout=240
                )
                if resp.status_code != 200:
                    st.error(f"Backend error: {resp.status_code} - {resp.text}")
                else:
                    data = resp.json()
                    st.subheader("Summary:")
                    st.write(data["summary"])

                    if recipient_email:
                        if data.get("emailed"):
                            st.success(f"Summary emailed to {recipient_email}")
                        else:
                            st.warning(
                                "Summary generated, but email could not be sent. "
                                "Check email configuration."
                            )
            except Exception as e:
                st.error(f"Error contacting backend: {e}")
