import os
import io
from typing import Optional

import requests
import streamlit as st

# Optional PDF support – comment out if you don't have PyPDF2 installed
try:
    from PyPDF2 import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

# ---------------------------
# Page config
# ---------------------------
st.set_page_config(
    page_title="Upload Data – AI Report",
    page_icon="📄",
    layout="wide",
)

# ---------------------------
# Helpers
# ---------------------------

def get_backend_url() -> Optional[str]:
    """
    Read the backend URL from the Streamlit environment.
    On Render you have BACKEND_URL defined in the ai-report-saas service.
    """
    return os.getenv("BACKEND_URL")


def read_file_to_text(upload) -> str:
    """
    Convert the uploaded file into plain text for the summarizer.
    Supports txt / md / markdown / pdf / docx / csv (best-effort).
    """
    if upload is None:
        return ""

    name = upload.name.lower()

    # Read bytes once
    raw = upload.read()

    # Text-like formats
    if name.endswith((".txt", ".md", ".markdown", ".csv")):
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return raw.decode("latin-1", errors="ignore")

    # Simple DOCX support (best effort, no extra dependency)
    if name.endswith(".docx"):
        try:
            import zipfile
            from xml.etree import ElementTree

            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                with z.open("word/document.xml") as doc_xml:
                    tree = ElementTree.parse(doc_xml)
                    root = tree.getroot()
                    # DOCX text nodes are in <w:t> tags
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    texts = [node.text for node in root.findall(".//w:t", ns) if node.text]
                    return "\n".join(texts)
        except Exception:
            # Fallback to naive decode
            return raw.decode("utf-8", errors="ignore")

    # PDF using PyPDF2 if available
    if name.endswith(".pdf") and PdfReader is not None:
        try:
            reader = PdfReader(io.BytesIO(raw))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)
        except Exception:
            # Fallback to raw bytes if extraction fails
            return raw.decode("utf-8", errors="ignore")

    # Last resort: dump bytes as text
    return raw.decode("utf-8", errors="ignore")


def summarize_via_backend(text: str, email: str, plan: str = "free") -> str:
    """
    Call the FastAPI backend /summarize endpoint.
    """
    backend = get_backend_url()
    if not backend:
        raise RuntimeError("BACKEND_URL is not configured in the Streamlit environment.")

    url = backend.rstrip("/") + "/summarize"

    payload = {
        "email": email or "anonymous@example.com",
        "plan": plan,
        "text": text,
    }

    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # Expecting {"summary": "..."} from the backend
    return data.get("summary", "").strip()


# ---------------------------
# UI
# ---------------------------

st.title("Upload Data & Generate a Business-Friendly Summary")

st.write(
    "Turn dense reports, meeting notes, and long documents into a clear, client-ready summary "
    "you can drop into emails, slide decks, or status updates."
)

# Email (used to link subscription + summaries)
st.subheader("Your email")
st.caption("Use the same email address you subscribed with on the Billing page.")

default_email = st.session_state.get("user_email", "")
email = st.text_input("Email address", value=default_email, placeholder="you@example.com")

if email and email != default_email:
    st.session_state["user_email"] = email

# Plan / status banner (purely informational; backend can still enforce limits)
plan = st.session_state.get("subscription_plan", "Free").capitalize()
st.markdown(
    f"**Status:** {plan} plan  \n"
    "Upload limits and summary depth may vary based on your current subscription."
)

st.markdown("---")

# ---------------------------
# 1. Add content
# ---------------------------
st.header("1. Add your content")

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Upload a file")
    st.caption("Supported formats: TXT, MD, MARKDOWN, PDF, DOCX, CSV (max 200MB per file).")

    uploaded_file = st.file_uploader(
        "Drag and drop file here",
        type=["txt", "md", "markdown", "pdf", "docx", "csv"],
        help="Upload the report, meeting notes, or document you want summarized.",
    )

with col_right:
    st.subheader("Or paste text manually")
    manual_text = st.text_area(
        "Paste meeting notes, reports, or any free-text content.",
        height=260,
        placeholder="Paste your report or notes here if you prefer not to upload a file...",
    )

st.info("Upload a file or paste text on the right to get started.")

st.markdown("---")

# ---------------------------
# 2. Generate summary
# ---------------------------
st.header("2. Generate a summary")

# Decide which source we're using
source_text = ""
source_label = ""

if uploaded_file is not None:
    source_text = read_file_to_text(uploaded_file)
    source_label = f"file **{uploaded_file.name}**"
elif manual_text.strip():
    source_text = manual_text.strip()
    source_label = "pasted text"

if source_text:
    detected_chars = len(source_text)
    st.caption(f"Detected ~{detected_chars:,} characters in your {source_label}.")
else:
    st.caption("No content detected yet – upload a file or paste some text above.")

generate_clicked = st.button("Generate Business Summary", type="primary")

summary_placeholder = st.empty()

if generate_clicked:
    if not source_text:
        st.warning("Please upload a file or paste some text before generating a summary.")
    elif not email:
        st.warning("Please enter your email address so we can link your summaries to your subscription.")
    else:
        with st.spinner("Generating your business-friendly summary…"):
            try:
                summary = summarize_via_backend(source_text, email=email, plan=plan.lower())
                if summary:
                    st.success("Summary generated successfully.")
                    summary_placeholder.markdown(
                        "### Summary for your client or audience\n\n" + summary
                    )
                else:
                    st.warning(
                        "No summary was returned. You may want to try with a shorter input "
                        "or check your API configuration."
                    )
            except requests.exceptions.RequestException as e:
                st.error(
                    f"Summarization failed. Details: {type(e).__name__}: {e}"
                )
            except Exception as e:
                st.error(f"Unexpected error while summarizing: {e}")

st.markdown("---")

st.header("What this tool does for you")

st.markdown(
    """
- **Saves time** – Turn dense reports and notes into short, readable summaries.
- **Improves clarity** – Highlight key points, risks, decisions, and next steps.
- **Helps communication** – Quickly share updates with clients, managers, or your team.
"""
)
