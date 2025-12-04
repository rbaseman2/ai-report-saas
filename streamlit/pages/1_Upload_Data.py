import os
from io import BytesIO

import requests
import streamlit as st

# Optional imports for richer file support
try:
    from PyPDF2 import PdfReader
except Exception:  # library might not be installed
    PdfReader = None

try:
    from docx import Document
except Exception:
    Document = None

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

st.set_page_config(
    page_title="Upload Data – AI Report",
    page_icon="📄",
    layout="wide",
)


# ---------- Helpers ----------


def read_text_from_file(uploaded_file) -> str:
    """Extract text from an uploaded file (txt, md, csv, pdf, docx)."""
    name = (uploaded_file.name or "").lower()

    # Plain text-like
    if name.endswith((".txt", ".md", ".csv")):
        try:
            return uploaded_file.getvalue().decode("utf-8", errors="ignore")
        except Exception:
            return uploaded_file.read().decode("utf-8", errors="ignore")

    # PDF
    if name.endswith(".pdf") and PdfReader is not None:
        reader = PdfReader(BytesIO(uploaded_file.getvalue()))
        chunks = []
        for page in reader.pages:
            text = page.extract_text() or ""
            chunks.append(text)
        return "\n".join(chunks)

    # DOCX
    if name.endswith(".docx") and Document is not None:
        doc = Document(BytesIO(uploaded_file.getvalue()))
        return "\n".join(p.text for p in doc.paragraphs)

    # Fallback: try to decode as text
    try:
        return uploaded_file.getvalue().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def call_summarize(email: str, text: str) -> str:
    """Call backend /summarize and return the summary text."""
    resp = requests.post(
        f"{BACKEND_URL}/summarize",
        json={"email": email, "text": text},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json() or {}

    # Backend could return { "summary": "..." } or plain string; support both.
    if isinstance(data, dict):
        return data.get("summary", "") or data.get("result", "") or str(data)
    return str(data)


# ---------- Page UI ----------

st.title("Upload Data & Generate a Business-Friendly Summary")

if not BACKEND_URL:
    st.error(
        "BACKEND_URL environment variable is not set for the Streamlit app. "
        "Set it in Render → ai-report-saas → Environment so this page can "
        "talk to the backend."
    )
    st.stop()

st.caption(
    "Turn dense reports, meeting notes, and long documents into a clear, "
    "client-ready summary you can drop into emails, slide decks, or status updates."
)

# Email (pulled from billing if available)
default_email = st.session_state.get("billing_email", "")
email = st.text_input(
    "Your email (must match your billing email)",
    value=default_email,
    placeholder="you@company.com",
)

if default_email and not email:
    # User manually cleared it
    st.info("This should match the email you used on the **Billing** page.")

# Optional plan info stored on billing
plan_info = st.session_state.get(
    "plan_info",
    {"plan": "free", "max_documents": 5, "max_chars": 200_000},
)

plan_label = (plan_info.get("plan") or "free").capitalize()
max_docs = plan_info.get("max_documents", 5)
max_chars = plan_info.get("max_chars", 200_000)

with st.container():
    st.markdown(
        f"**Status:** {plan_label} plan – you can upload up to "
        f"**{max_docs} documents** and approximately **{max_chars:,} "
        f"characters** per month."
    )
    st.caption(
        "Limits are enforced on the backend per email address. "
        "If you hit a limit, you can always upgrade on the **Billing** tab."
    )

st.markdown("### 1. Add your content")

left, right = st.columns([1.4, 1.1])

with left:
    uploaded_file = st.file_uploader(
        "Upload a report file",
        type=["txt", "md", "pdf", "docx", "csv"],
        help="TXT, MD, PDF, DOCX, or CSV – max 200 MB per file.",
    )

    manual_text = st.text_area(
        "Or paste text manually",
        placeholder="Paste meeting notes, reports, or any free-text content…",
        height=220,
    )

with right:
    st.write("**Tips for best results**")
    st.markdown(
        "- Upload one report at a time for the cleanest summary.\n"
        "- Very large PDFs may be truncated based on your plan limits.\n"
        "- Make sure you’ve saved your billing email on the **Billing** page."
    )

st.markdown("### 2. Generate a summary")

summary_button = st.button("Generate Business Summary", type="primary")

# Optional debug of payload (helpful during dev – safe to leave since it’s behind expander)
with st.expander("Debug: request payload being sent to /summarize"):
    st.write(
        "We send your **email** and the combined text from your upload and "
        "manual input to the backend:"
    )
    st.code(
        "{ 'email': '<your email>', 'text': '<combined text ...>' }",
        language="json",
    )

if summary_button:
    if not email.strip():
        st.error("Please enter your email (matching the Billing page) first.")
    else:
        combined_parts = []

        if uploaded_file is not None:
            file_text = read_text_from_file(uploaded_file)
            if not file_text.strip():
                st.warning(
                    f"Could not extract text from **{uploaded_file.name}**. "
                    "Try saving it as a TXT or PDF and re-uploading."
                )
            else:
                combined_parts.append(file_text)

        if manual_text.strip():
            combined_parts.append(manual_text.strip())

        full_text = "\n\n".join(combined_parts).strip()

        if not full_text:
            st.error(
                "Please upload a file, paste some text, or both before "
                "requesting a summary."
            )
        else:
            try:
                with st.spinner("Generating your business-friendly summary…"):
                    summary = call_summarize(email=email.strip(), text=full_text)

                if not summary:
                    st.warning(
                        "The backend returned an empty summary. "
                        "If this keeps happening, check the backend logs."
                    )
                else:
                    st.success("Summary ready! 🎉")
                    st.markdown("#### AI-generated summary")
                    st.markdown(summary)

                    st.markdown("---")
                    st.caption(
                        "You can copy-paste this summary into emails, reports, or "
                        "slide decks. For another document, upload a new file or "
                        "paste new text and click **Generate Business Summary** again."
                    )

            except requests.HTTPError as http_err:
                try:
                    data = http_err.response.json()
                except Exception:
                    data = None
                if isinstance(data, dict) and data.get("detail"):
                    st.error(f"Backend returned error: {data['detail']}")
                else:
                    st.error(f"Backend HTTP error: {http_err}")
            except Exception as exc:
                st.error(f"Network or backend error while summarizing: {exc}")
