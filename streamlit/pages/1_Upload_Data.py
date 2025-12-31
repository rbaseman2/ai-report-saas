import os
import io
import requests
import streamlit as st

# ----------------------------
# Config
# ----------------------------
BACKEND_URL = os.getenv("BACKEND_URL") or os.getenv("BACKEND_API_URL") or ""
if BACKEND_URL.endswith("/"):
    BACKEND_URL = BACKEND_URL[:-1]

st.set_page_config(page_title="Upload Data", layout="wide")

st.title("Upload Data")

if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set.")
    st.stop()

# ----------------------------
# Helpers
# ----------------------------
def extract_text_from_upload(uploaded_file) -> str:
    """
    Best-effort text extraction:
      - txt/csv/md/json/xml -> decode
      - pdf -> PyPDF2 if installed
      - docx -> python-docx if installed
    """
    filename = uploaded_file.name.lower()
    data = uploaded_file.getvalue()

    # Plain text-ish
    if filename.endswith((".txt", ".csv", ".md", ".json", ".xml", ".log")):
        return data.decode("utf-8", errors="ignore")

    # PDF
    if filename.endswith(".pdf"):
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            text = "\n".join(parts).strip()
            return text
        except Exception:
            return ""

    # DOCX
    if filename.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs if p.text]
            return "\n".join(parts).strip()
        except Exception:
            return ""

    # Unknown type
    return ""

def post_generate_summary(billing_email: str, recipient_email: str, content: str):
    url = f"{BACKEND_URL}/generate-summary"
    payload = {
        "email": billing_email,
        "recipient_email": recipient_email,
        "content": content,
    }
    r = requests.post(url, json=payload, timeout=60)
    return r

# ----------------------------
# UI
# ----------------------------
st.subheader("1. Upload a file OR paste text")

uploaded = st.file_uploader(
    "Upload a document (TXT/CSV/MD/JSON/XML/PDF/DOCX)",
    type=["txt", "csv", "md", "json", "xml", "log", "pdf", "docx"],
)

manual_text = st.text_area("Or paste text manually", height=220)

st.subheader("2. Generate a summary")

send_email = st.checkbox("Email this summary to someone", value=True)

recipient_email = st.text_input("Recipient email", value=os.getenv("DEFAULT_RECIPIENT_EMAIL", ""))
billing_email = st.text_input(
    "Billing email (used for subscription association)",
    value=os.getenv("DEFAULT_BILLING_EMAIL", ""),
    help="This should match the email used on the Billing page / subscription.",
)

if st.button("Generate Business Summary"):
    # Build content
    content = ""
    if uploaded is not None:
        content = extract_text_from_upload(uploaded)

        if not content and not manual_text.strip():
            st.error(
                "Could not extract text from that file type in the frontend. "
                "Try TXT, or paste the text manually for now."
            )
            st.stop()

    # Prefer extracted content; fallback to manual
    if not content:
        content = manual_text.strip()

    if not content:
        st.error("No content provided. Upload a file or paste text.")
        st.stop()

    if not billing_email.strip():
        st.error("Billing email is required.")
        st.stop()

    if send_email and not recipient_email.strip():
        st.error("Recipient email is required when 'Email this summary' is checked.")
        st.stop()

    with st.spinner("Sending to backend..."):
        try:
            r = post_generate_summary(
                billing_email=billing_email.strip(),
                recipient_email=recipient_email.strip() if send_email else billing_email.strip(),
                content=content,
            )
        except Exception as e:
            st.error(f"Request failed: {e}")
            st.stop()

    if r.status_code == 200:
        st.success("✅ Summary generated and email sent.")
        st.json(r.json())
    else:
        st.error(f"Backend error {r.status_code}")
        st.code(r.text)
