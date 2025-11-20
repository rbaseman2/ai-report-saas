import os
import io
import requests
import streamlit as st

from typing import Optional

# Must be first Streamlit call
st.set_page_config(
    page_title="Upload Data – AI Report",
    page_icon="📄",
    layout="wide",
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

# ---------- Helpers ----------


def extract_text_from_file(uploaded_file) -> str:
    """Convert an uploaded file into plain text."""
    if uploaded_file is None:
        return ""

    name = uploaded_file.name.lower()
    data = uploaded_file.read()

    # Make sure we can read it more than once
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)

    # Simple text formats
    if name.endswith((".txt", ".md", ".markdown")):
        return data.decode("utf-8", errors="ignore")

    # CSV -> treat as text table
    if name.endswith(".csv"):
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    # PDF
    if name.endswith(".pdf"):
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = []
            for page in reader.pages:
                text = page.extract_text() or ""
                pages.append(text)
            return "\n\n".join(pages)
        except Exception:
            return ""

    # Word .docx
    if name.endswith(".docx"):
        try:
            import docx  # python-docx

            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return ""

    # Fallback: try decode as text
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def call_summarization_api(text: str, email: Optional[str] = None) -> str:
    """Call the backend /summarize endpoint and return the summary text."""
    try:
        payload = {"text": text}
        if email:
            payload["email"] = email

        response = requests.post(f"{BACKEND_URL}/summarize", json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data.get("summary", "").strip()
    except Exception as exc:
        st.error(f"Summarization failed. Details: {exc}")
        return ""


# ---------- Page UI ----------

st.title("Upload Data & Generate a Business-Friendly Summary")

# Query params (e.g. after returning from Stripe)
params = st.query_params
status = params.get("status")

if status == "success":
    st.success(
        "Your subscription was completed successfully. "
        "You can now continue using AI Report with your selected plan."
    )
elif status == "cancelled":
    st.info("Checkout was cancelled. You can try again from the Billing page at any time.")

st.markdown("### Your email")
st.caption("Use the same email you used when subscribing so we can keep things linked.")

default_email = st.session_state.get("user_email", "")
email = st.text_input("Email address", value=default_email, key="upload_email")

if email:
    st.session_state["user_email"] = email

# You can optionally wire this to a real plan/status endpoint later
st.markdown("### Status")
st.info(
    "You’re currently using AI Report. Plan-specific limits can be enforced later via the backend, "
    "but you can already upload and summarize documents."
)

st.markdown("---")

st.markdown("## 1. Add your content")

left, right = st.columns(2)

with left:
    st.markdown("#### Upload a file")
    st.caption("Supported formats: TXT, MD, PDF, DOCX, CSV (max 200MB per file).")

    uploaded_file = st.file_uploader(
        "Drag and drop a file here, or click **Browse files**.",
        type=["txt", "md", "markdown", "pdf", "docx", "csv"],
        label_visibility="collapsed",
    )

with right:
    st.markdown("#### Or paste text manually")
    manual_text = st.text_area(
        "Paste meeting notes, reports, or any free-text content.",
        height=260,
    )

source_text = ""

if uploaded_file is not None:
    source_text = extract_text_from_file(uploaded_file)
elif manual_text.strip():
    source_text = manual_text.strip()

if source_text:
    st.markdown("---")
    st.markdown("### 2. Generate a summary")

    char_count = len(source_text)
    st.caption(f"Detected **{char_count:,}** characters in your input.")

    if st.button("Generate Business Summary", type="primary"):
        with st.spinner("Analyzing your document and creating a summary..."):
            summary = call_summarization_api(source_text, email=email)

        st.markdown("### Summary for your client or audience")
        if summary:
            st.write(summary)
        else:
            st.warning(
                "No summary was returned. You may want to try with a shorter input or check your API configuration."
            )
else:
    st.info("Upload a file or paste text on the right to get started.")

st.markdown("---")

st.markdown(
    """
### What this tool does for you

- **Saves time** – Turn dense reports and notes into short, readable summaries  
- **Improves clarity** – Highlight key points, risks, decisions, and next steps  
- **Helps communication** – Quickly share updates with clients, managers, or your team  
"""
)
