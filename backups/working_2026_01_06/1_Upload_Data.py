"""
streamlit/1_Upload_Data.py

Restores the original user flow:
- Upload PDF (or paste text)
- Generate summary (optionally email it) directly from this page

Still supports storing upload_id (so Billing can also use it if desired).
"""
from __future__ import annotations

import os
import requests
import streamlit as st

st.set_page_config(page_title="Upload Data", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL") or os.getenv("BACKEND_API_URL") or ""
if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set.")
    st.stop()

st.title("Upload Data")

# --- Inputs
uploaded_file = st.file_uploader("Upload a document (PDF)", type=["pdf"], accept_multiple_files=False)
manual_text = st.text_area("Or paste text manually", height=180)

account_email = st.text_input("Account Email (used to check subscription)", value=st.session_state.get("billing_email", ""))
recipient_email = st.text_input("Recipient email (optional)", value=st.session_state.get("recipient_email", ""))
email_summary = st.checkbox("Email this summary to recipient", value=bool(recipient_email))

col1, col2 = st.columns([1, 2])

def call_upload(file_obj, acct_email: str) -> str:
    files = {"file": (file_obj.name, file_obj.getvalue(), file_obj.type or "application/pdf")}
    data = {"account_email": acct_email}
    r = requests.post(f"{BACKEND_URL}/upload", files=files, data=data, timeout=60)
    r.raise_for_status()
    return r.json()["upload_id"]

def call_generate_summary(file_obj=None, content_text: str = "", upload_id: str = "", recipient: str = "", do_email: bool = False):
    # Prefer multipart (it avoids JSON bytes/encoding issues and works with PDF directly)
    files = {}
    data = {
        "content": content_text or "",
        "upload_id": upload_id or "",
        "recipient_email": recipient or "",
        "email_summary": "true" if do_email else "false",
    }
    if file_obj is not None:
        files["file"] = (file_obj.name, file_obj.getvalue(), file_obj.type or "application/pdf")

    r = requests.post(f"{BACKEND_URL}/generate-summary", files=files or None, data=data, timeout=120)
    r.raise_for_status()
    return r.json()

with col1:
    if st.button("Generate Summary", type="primary", use_container_width=True):
        try:
            # Keep convenience state
            if account_email:
                st.session_state["billing_email"] = account_email
            if recipient_email:
                st.session_state["recipient_email"] = recipient_email

            upload_id = st.session_state.get("upload_id", "")

            # If a new file was provided, (re)upload it so we have an upload_id for future pages too.
            if uploaded_file is not None:
                upload_id = call_upload(uploaded_file, account_email or "unknown@example.com")
                st.session_state["upload_id"] = upload_id

            resp = call_generate_summary(
                file_obj=uploaded_file,
                content_text=manual_text,
                upload_id=upload_id,
                recipient=recipient_email if email_summary else "",
                do_email=email_summary and bool(recipient_email),
            )

            st.session_state["last_summary"] = resp.get("summary", "")
            st.success("Summary generated." + (" Email sent." if resp.get("emailed") else ""))
        except requests.HTTPError as e:
            st.error(f"Backend error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            st.error(f"Unexpected error: {e}")

with col2:
    st.markdown("### Output")
    summary = st.session_state.get("last_summary", "")
    if summary:
        st.text_area("Summary", value=summary, height=320)
    else:
        st.info("Upload a file or paste text, then click **Generate Summary**.")

st.caption("Tip: After a successful upload, Billing can still use upload_id stored in session_state if needed.")
