import streamlit as st
import requests
import os
import io

# Optional imports – we won't crash if they're missing
try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import docx2txt
except ImportError:
    docx2txt = None

st.set_page_config(page_title="Upload Data – AI Report")

BACKEND_URL = os.getenv("BACKEND_URL", "https://ai-report-backend-ubrx.onrender.com")

st.title("Upload Data & Generate a Business-Friendly Summary")

# -------------------------------------------------------------------
# Extract text from uploaded files
# -------------------------------------------------------------------

def extract_text_from_file(file):
    name = file.name.lower()

    # Plain text / markdown / csv: just decode
    if name.endswith((".txt", ".md", ".csv")):
        try:
            return file.read().decode("utf-8", errors="ignore")
        except Exception:
            return ""

    # PDF via pdfplumber (if available)
    if name.endswith(".pdf"):
        if pdfplumber is None:
            st.warning("PDF support requires the 'pdfplumber' package. "
                       "Ask your dev (you 🙂) to add 'pdfplumber' to requirements.txt.")
            return ""
        try:
            with pdfplumber.open(io.BytesIO(file.read())) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:
            st.error(f"Error reading PDF: {e}")
            return ""

    # DOCX via docx2txt (if available)
    if name.endswith(".docx"):
        if docx2txt is None:
            st.warning("DOCX support requires the 'docx2txt' package. "
                       "Add 'docx2txt' to requirements.txt.")
            return ""
        try:
            return docx2txt.process(file)
        except Exception as e:
            st.error(f"Error reading DOCX: {e}")
            return ""

    # Fallback
    st.warning(f"Unsupported file type for: {file.name}")
    return ""


# -------------------------------------------------------------------
# Email input (required by backend for entitlement)
# -------------------------------------------------------------------

email = st.text_input(
    "Your email",
    placeholder="Enter the same email you subscribed with",
    help="Use the same email you used at checkout so your plan & limits match."
)

st.markdown("---")

# -------------------------------------------------------------------
# File Upload
# -------------------------------------------------------------------

uploaded_files = st.file_uploader(
    "Upload a report file (TXT, MD, PDF, DOCX, CSV).",
    type=["txt", "md", "pdf", "docx", "csv"],
    accept_multiple_files=True
)

manual_text = st.text_area("Or paste text manually")

# -------------------------------------------------------------------
# GENERATE SUMMARY
# -------------------------------------------------------------------

st.subheader("2. Generate a summary")

send_email = st.checkbox("Email this summary to someone")
recipient_email = None
if send_email:
    recipient_email = st.text_input("Recipient email")

if st.button("Generate Business Summary"):

    if not email:
        st.error("Email is required.")
        st.stop()

    # -------- Extract text from uploads --------
    extracted_text = ""

    if uploaded_files:
        for f in uploaded_files:
            extracted_text += extract_text_from_file(f) + "\n"

    if manual_text.strip():
        extracted_text += manual_text.strip()

    if not extracted_text.strip():
        st.error("No text found. Upload a file or paste text manually.")
        st.stop()

    # -------- Truncate if extremely large --------
    max_chars = 200_000
    safe_text = extracted_text[:max_chars]

    payload = {
        "email": email,
        "text": safe_text,
        "send_email": send_email,
        "recipient_email": recipient_email,
    }

    # Optional debug
    # st.json(payload)

    try:
        response = requests.post(f"{BACKEND_URL}/summarize", json=payload, timeout=300)

        if response.status_code != 200:
            st.error(f"Backend error: {response.status_code}\n\n{response.text}")
        else:
            data = response.json()
            st.subheader("Summary:")
            st.write(data.get("summary", ""))

            if data.get("emailed"):
                st.success(f"Summary emailed to {recipient_email}")

    except Exception as e:
        st.error(f"Network or backend error: {e}")
