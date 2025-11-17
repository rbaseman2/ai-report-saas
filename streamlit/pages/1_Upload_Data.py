import os
import io
from typing import Tuple

import requests
import streamlit as st


# ---------- Config & helpers ----------

st.set_page_config(page_title="Upload Data", page_icon="📄", layout="wide")


def _get_backend_url() -> str:
    """
    Get the backend URL from environment variables only.

    Using st.secrets without a secrets.toml on Render causes that
    "No secrets found" warning banner, so we avoid it here.
    """
    return os.getenv("BACKEND_URL", "").rstrip("/")


BACKEND_URL = _get_backend_url()


def read_uploaded_file(uploaded_file) -> Tuple[str, str]:
    """
    Turn an uploaded file into plain text.

    Supports: .txt, .md, .csv, .pdf
    Returns (text, filename)
    """
    if uploaded_file is None:
        return "", ""

    filename = uploaded_file.name
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    # Simple text-like formats
    if ext in {".txt", ".md", ".csv"}:
        raw = uploaded_file.getvalue()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="ignore")
        return text, filename

    # PDF – requires pypdf in requirements.txt
    if ext == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return "", filename

        try:
            reader = PdfReader(uploaded_file)
            pages = [(p.extract_text() or "") for p in reader.pages]
            return "\n\n".join(pages), filename
        except Exception:
            return "", filename

    # Unknown
    return "", filename


# ---------- Page UI ----------

st.title("Upload Data & Generate a Patient-Friendly Summary")

# --- Email field (to tie uploads to subscription / summaries) ---
st.subheader("Your email")
st.caption("Use the same email you subscribed with.")
email = st.text_input("Email address", placeholder="you@example.com", label_visibility="collapsed")

# --- Plan status banner (simple for now – default to Free) ---
plan = st.session_state.get("plan_name", "Free")
status_col1, status_col2 = st.columns([1, 4])
with status_col1:
    st.write("**Status:**")
with status_col2:
    st.write(f"🟦 {plan}")

# Hint about free vs premium
if plan.lower() == "free":
    st.info(
        "You're on the free tier. Summaries are shorter and input size is limited. "
        "Upgrade on the **Billing** page for full access."
    )

st.markdown("---")

# ---------- 1. Upload content ----------

st.subheader("1. Add your consultation content")

left_col, right_col = st.columns(2)

with left_col:
    st.markdown("**Upload consultation notes or a report**")
    uploaded_file = st.file_uploader(
        "Drag and drop file here",
        type=["txt", "md", "pdf", "csv"],
        accept_multiple_files=False,
        help="Supported formats: TXT, MD, PDF, CSV",
    )
    if uploaded_file is not None:
        st.caption(f"Selected file: `{uploaded_file.name}`")

with right_col:
    st.markdown("**Or paste text manually**")
    pasted_text = st.text_area(
        "Paste consultation notes, HPI, assessment/plan, or any free-text report here…",
        height=260,
        label_visibility="collapsed",
    )

file_text, filename = read_uploaded_file(uploaded_file)
all_text = (file_text or "") + ("\n\n" + pasted_text if pasted_text.strip() else "")

char_count = len(all_text)
st.caption(f"Detected ~{char_count} characters in total from your upload and pasted text.")

st.markdown("---")

# ---------- 2. Generate summary ----------

st.subheader("2. Generate a summary")

summary_placeholder = st.empty()

generate_clicked = st.button("Generate Patient-Friendly Summary", type="primary")

if generate_clicked:
    # Basic validation
    if not email.strip():
        st.error("Please enter your email so we can link this summary to your subscription.")
    elif not all_text.strip():
        st.error("Please upload a file or paste some text before generating a summary.")
    elif not BACKEND_URL:
        st.error("BACKEND_URL is not configured. Please set it in Streamlit secrets or env vars.")
    else:
        with st.spinner("Talking to the AI and generating your summary…"):
            try:
                response = requests.post(
                    f"{BACKEND_URL}/summarize",
                    json={
                        "email": email.strip(),
                        "text": all_text,
                        "filename": filename,
                    },
                    timeout=90,
                )
            except requests.RequestException as e:
                st.error(f"Network error calling backend: {e}")
            else:
                if response.status_code != 200:
                    # Show error returned by backend
                    try:
                        payload = response.json()
                        detail = payload.get("detail") or payload
                    except Exception:
                        detail = response.text
                    st.error(f"Summarization failed ({response.status_code}): {detail}")
                else:
                    data = response.json() or {}
                    summary = data.get("summary", "").strip()
                    if not summary:
                        st.warning("No summary text was returned. Try with a shorter or clearer input.")
                    else:
                        st.success("Summary generated successfully 🎉")
                        summary_placeholder.text_area(
                            "Summary for the patient",
                            value=summary,
                            height=260,
                        )

# ---------- Footer ----------

st.markdown("---")
st.caption(
    "This tool helps convert dense clinical or technical notes into a patient-friendly summary. "
    "For best results, use clear, complete documentation and avoid uploading images or scans."
)
if BACKEND_URL:
    st.caption(f"Using backend: `{BACKEND_URL}`")
