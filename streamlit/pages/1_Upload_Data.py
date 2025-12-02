# 1_Upload_Data.py – fixed so email is always sent to /summarize

import os
import requests
import streamlit as st

# ---------------------------------------------------------------------
# Streamlit config MUST be first Streamlit call
# ---------------------------------------------------------------------
st.set_page_config(page_title="Upload Data – AI Report", page_icon="📄")

# ---------------------------------------------------------------------
# Backend config
# ---------------------------------------------------------------------
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubx.onrender.com"  # update if your URL changes
)

st.title("Upload Data & Generate a Business-Friendly Summary")
st.write(
    "Turn dense reports, meeting notes, and long documents into clear, client-ready summaries."
)

# ---------------------------------------------------------------------
# Email used for billing & summarization
# ---------------------------------------------------------------------
st.subheader("Your email")

# Get any email already stored from the Billing page
saved_email = st.session_state.get("billing_email", "")

email_input = st.text_input(
    "Use the same email you subscribed with:",
    value=saved_email,
    placeholder="you@example.com",
)

# Keep session in sync so Billing & Upload share the same address
if email_input:
    st.session_state["billing_email"] = email_input

if not email_input:
    st.info("Enter your billing email above before generating a summary.")

# ---------------------------------------------------------------------
# Upload or paste content
# ---------------------------------------------------------------------
st.subheader("1. Add your content")

uploaded_file = st.file_uploader(
    "Upload a report file (TXT, MD, PDF, DOCX, CSV).",
    type=["txt", "md", "pdf", "docx", "csv"],
)

manual_text = st.text_area(
    "Or paste text manually",
    height=200,
    placeholder="Paste meeting notes, reports, or any free-text content…",
)

content_text = ""
filename = "manual_input.txt"

if uploaded_file is not None:
    filename = uploaded_file.name
    try:
        content_text = uploaded_file.read().decode("utf-8", errors="ignore")
    except Exception:
        content_text = ""
elif manual_text.strip():
    content_text = manual_text.strip()

# ---------------------------------------------------------------------
# Generate summary
# ---------------------------------------------------------------------
st.subheader("2. Generate a summary")

if st.button("Generate Business Summary", type="primary"):
    # Basic validation
    if not email_input:
        st.error("Please enter the email you used at checkout.")
        st.stop()

    if not content_text:
        st.error("Please upload a file or paste some text before summarizing.")
        st.stop()

    payload = {
        "email": email_input,
        "text_content": content_text,
        "filename": filename,
        "num_chars": len(content_text),
    }

    with st.spinner("Contacting the AI engine…"):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/summarize",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

            st.success("Summary generated successfully!")
            summary_text = data.get("summary", "")
            if summary_text:
                st.markdown("### Summary")
                st.write(summary_text)
            else:
                st.warning("Backend responded without a 'summary' field.")

        except requests.exceptions.RequestException as e:
            st.error(f"Network or backend error: {e}")
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            try:
                st.json(resp.json())
            except Exception:
                pass
