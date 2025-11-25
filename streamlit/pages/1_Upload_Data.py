# streamlit/pages/1_Upload_Data.py

import os
import io
from typing import Optional, Tuple

import requests
import streamlit as st

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------

BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",  # default so local dev still works
)

st.set_page_config(
    page_title="Upload Data – AI Report",
    page_icon="📄",
)

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def check_subscription(email: str) -> Tuple[dict, Optional[str]]:
    """
    Ask the backend which plan (if any) this email is on.

    Returns (subscription_info, error_message).
    If there's an error, subscription_info will fall back to a "free" plan.
    """
    if not email:
        return {"plan": "free", "label": "Free plan"}, "Please enter an email first."

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscriptions/verify",
            params={"email": email},
            timeout=10,
        )
    except Exception as exc:
        return (
            {"plan": "free", "label": "Free plan"},
            f"Could not reach backend while checking subscription: {exc}",
        )

    if resp.status_code == 200:
        data = resp.json() or {}
        plan = data.get("plan", "free") or "free"
        label = data.get("label") or f"{plan.capitalize()} plan"
        max_chars = data.get("max_chars")
        max_docs = data.get("max_docs_per_month")

        info = {
            "plan": plan,
            "label": label,
            "max_chars": max_chars,
            "max_docs_per_month": max_docs,
        }
        return info, None

    if resp.status_code == 404:
        # No active subscription – treat as free
        return (
            {"plan": "free", "label": "Free plan"},
            None,
        )

    # Any other status code
    return (
        {"plan": "free", "label": "Free plan"},
        f"Backend returned {resp.status_code} when checking subscription.",
    )


def read_text_from_file(uploaded_file) -> str:
    """
    Turn an uploaded file into plain text for the summarizer.

    This is intentionally simple and defensive – it handles the common formats
    that are easy to parse in a Streamlit app without extra heavy dependencies.
    """
    if uploaded_file is None:
        return ""

    name = uploaded_file.name.lower()

    # Always read bytes; we'll decode or hand off as needed.
    raw_bytes = uploaded_file.read()
    if not raw_bytes:
        return ""

    # Simple text-ish types just decode as UTF-8 with replacement.
    if name.endswith((".txt", ".md", ".markdown", ".csv")):
        try:
            return raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            return raw_bytes.decode("latin-1", errors="replace")

    # DOCX support (if the dependency is installed)
    if name.endswith(".docx"):
        try:
            import docx2txt  # type: ignore

            # docx2txt expects a file path; we can fake one with BytesIO
            with io.BytesIO(raw_bytes) as f:
                text = docx2txt.process(f)
            return text or ""
        except Exception:
            st.warning(
                "DOCX support requires the `docx2txt` package. "
                "You can also export your document to PDF or TXT and upload that."
            )
            return ""

    # PDF support (if PyPDF2 is installed)
    if name.endswith(".pdf"):
        try:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(io.BytesIO(raw_bytes))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n\n".join(pages)
        except Exception:
            st.warning(
                "PDF support requires the `PyPDF2` package. "
                "You can also copy-paste the text on the right-hand side."
            )
            return ""

    # Fallback – best-effort decode
    try:
        return raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return raw_bytes.decode("latin-1", errors="replace")


def call_summarize_api(email: str, content: str, plan: str) -> Tuple[Optional[str], str]:
    """
    Call the backend /summarize endpoint.

    Returns (summary_text_or_None, error_message_if_any).
    """
    payload = {
        "email": email,
        "content": content,
        "plan": plan,
    }

    try:
        resp = requests.post(
            f"{BACKEND_URL}/summarize",
            json=payload,
            timeout=90,
        )
    except Exception as exc:
        return None, f"Could not reach backend summarizer: {exc}"

    if resp.status_code == 200:
        data = resp.json() or {}
        summary = data.get("summary") or data.get("text")
        if not summary:
            return None, "Backend responded but did not return a summary."
        return summary, ""

    # Non-200 – surface a helpful error
    try:
        detail = resp.json()
    except Exception:
        detail = resp.text

    return None, f"Summarization failed ({resp.status_code}): {detail}"


# --------------------------------------------------------------------
# Session state initialisation
# --------------------------------------------------------------------

if "email" not in st.session_state:
    st.session_state.email = ""

if "subscription" not in st.session_state:
    st.session_state.subscription = {"plan": "free", "label": "Free plan"}

# --------------------------------------------------------------------
# Page UI
# --------------------------------------------------------------------

st.title("Upload Data & Generate a Business-Friendly Summary")
st.caption(
    "Turn dense reports, meeting notes, and long documents into a clear, "
    "client-ready summary you can drop into emails, slide decks, or status updates."
)

# --- Email + plan status ------------------------------------------------------

st.subheader("Your email")

email = st.text_input(
    "Use the same email address you subscribed with on the Billing page.",
    value=st.session_state.email,
    placeholder="you@example.com",
)

col_save, _ = st.columns([1, 4])
with col_save:
    if st.button("Save email & check plan", type="primary"):
        st.session_state.email = email.strip()
        sub_info, err = check_subscription(st.session_state.email)
        st.session_state.subscription = sub_info

        if err:
            st.warning(
                "We couldn’t verify your subscription just now, "
                "so we’re treating you as on the free plan for this session.\n\n"
                f"Technical details: {err}"
            )
        else:
            if sub_info["plan"] == "free":
                st.info(
                    "No active subscription found – you’re currently on the **Free plan**. "
                    "Summaries may be shorter and upload limits lower."
                )
            else:
                plan_label = sub_info.get("label") or sub_info["plan"].capitalize()
                st.success(f"Subscription verified – you’re on the **{plan_label}** 🎉")

# Status bar
plan_label = st.session_state.subscription.get("label", "Free plan")
st.write("**Status:**", plan_label)

limits_bits = []
max_chars = st.session_state.subscription.get("max_chars")
max_docs = st.session_state.subscription.get("max_docs_per_month")

if max_docs:
    limits_bits.append(f"up to **{max_docs}** documents per month")
if max_chars:
    limits_bits.append(f"up to **{max_chars:,}** characters per summary")

if limits_bits:
    st.caption("Upload limits for your plan: " + " • ".join(limits_bits))
else:
    st.caption(
        "Upload limits and summary depth may vary based on your current subscription."
    )

st.markdown("---")

# --- Section 1: Add content ---------------------------------------------------

st.subheader("1. Add your content")

left, right = st.columns(2)

with left:
    st.markdown("**Upload a file**")
    st.caption(
        "Supported formats: TXT, MD, MARKDOWN, PDF, DOCX, CSV (max 200MB per file)."
    )
    uploaded_file = st.file_uploader(
        "Drag and drop a file here",
        type=["txt", "md", "markdown", "pdf", "docx", "csv"],
        label_visibility="collapsed",
    )

with right:
    st.markdown("**Or paste text manually**")
    manual_text = st.text_area(
        "Paste meeting notes, reports, or any free-text content.",
        height=260,
        label_visibility="collapsed",
    )

# Build combined content + length diagnostics
file_text = ""
if uploaded_file is not None:
    file_text = read_text_from_file(uploaded_file)

combined_text = (file_text or "") + ("\n\n" + manual_text if manual_text.strip() else "")

char_count = len(combined_text)
if char_count > 0:
    st.write(f"Detected ~**{char_count:,}** characters in total from your upload and text.")

# --- Section 2: Generate summary ---------------------------------------------


st.subheader("2. Generate a summary")

if st.button("Generate Business Summary", type="primary"):
    if not st.session_state.email:
        st.error("Please enter and save your email before generating a summary.")
    elif not combined_text.strip():
        st.error("Please upload a file or paste some text to summarize.")
    else:
        plan = st.session_state.subscription.get("plan", "free")
        with st.spinner("Generating your business-friendly summary…"):
            summary, err = call_summarize_api(
                email=st.session_state.email,
                content=combined_text,
                plan=plan,
            )

        if err:
            st.error(err)
        else:
            st.success("Summary generated successfully.")
            st.markdown("### Summary for your client or audience")
            st.markdown(summary)

# --- Section 3: What this tool does ------------------------------------------

st.markdown("---")
st.subheader("What this tool does for you")

st.markdown(
    """
- **Saves time** – Turn dense reports and notes into short, readable summaries.
- **Improves clarity** – Highlight key points, risks, decisions, and next steps.
- **Helps communication** – Quickly share updates with clients, managers, or your team.
"""
)
