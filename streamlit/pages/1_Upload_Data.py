# 1_Upload_Data.py  – clean & fixed version

import os
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubx.onrender.com"   # <- change if needed
)

# -----------------------------------------------------------------------------
# Streamlit Page Setup
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Upload Data – AI Report", page_icon="📄")

st.title("Upload Data & Generate a Business-Friendly Summary")
st.write(
    "Turn dense reports, meeting notes, and long documents into clear summaries."
)

# -----------------------------------------------------------------------------
# Load the billing email saved on Billing page
# -----------------------------------------------------------------------------
if "billing_email" not in st.session_state:
    st.session_state["billing_email"] = ""

user_email = st.session_state["billing_email"]

if not user_email:
    st.warning(
        "⚠️ Please enter your email on the **Billing** page first. "
        "Your plan and limits are linked to your email."
    )

st.subheader("Your email")
st.text_input("Billing email (from Billing page):", value=user_email, disabled=True)

# -----------------------------------------------------------------------------
# File Upload + Text Input
# -----------------------------------------------------------------------------
st.subheader("1. Add your content")

uploaded_file = st.file_uploader(
    "Upload a report file (TXT, MD, PDF, DOCX, CSV).",
    type=["txt", "md", "pdf", "docx", "csv"],
)

manual_text = st.text_area(
    "Or paste text manually",
    height=200,
    placeholder="Paste meeting notes, reports, or any content..."
)

content_text = ""
filename = "manual_input.txt"

if uploaded_file:
    filename = uploaded_file.name
    try:
        content_text = uploaded_file.read().decode("utf-8", errors="ignore")
    except:
        content_text = ""

elif manual_text.strip():
    content_text = manual_text.strip()

# -----------------------------------------------------------------------------
# Generate Summary Button
# -----------------------------------------------------------------------------
st.subheader("2. Generate a summary")

if st.button("Generate Business Summary", type="primary"):

    if not user_email:
        st.error("Email missing. Please go to the Billing page and save your email first.")
        st.stop()

    if not content_text:
        st.error("Please upload a file or paste text before summarizing.")
        st.stop()

    payload = {
        "email": user_email,
        "text_content": content_text,
        "filename": filename,
        "num_chars": len(content_text),
    }

    with st.spinner("Contacting the AI engine..."):
        try:
            response = requests.post(
                f"{BACKEND_URL}/summarize",
                json=payload,
                timeout=120,
            )

            response.raise_for_status()
            data = response.json()

            st.success("Summary generated successfully!")
            st.write(data.get("summary", ""))

        except Exception as e:
            st.error(f"Backend error: {e}")
            st.json(response.json() if 'response' in locals() else {})

