import os
import io
from typing import Optional

import requests
import streamlit as st

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------

# Backend base URL – set this in Render as BACKEND_URL for the frontend
BACKEND_URL = os.environ.get(
    "BACKEND_URL",
    "https://ai-report-backend-ubrx.onrender.com",
).rstrip("/")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def get_subscription_status(email: str) -> tuple[str, Optional[str]]:
    """
    Call the backend to lookup the user's subscription status.

    Returns:
        (plan, error_message)
        plan: "free" | "basic" | "pro" | "enterprise"
        error_message: Optional error string if the call failed.
    """
    if not email:
        return "free", "No email provided."

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription_status",
            params={"email": email},
            timeout=10,
        )
        if resp.status_code != 200:
            return "free", f"Backend returned {resp.status_code} when checking subscription."

        data = resp.json()
        plan = str(data.get("plan", "free")).lower()
        if plan not in {"free", "basic", "pro", "enterprise"}:
            plan = "free"
        return plan, None
    except Exception as exc:
        return "free", f"Unable to reach backend: {exc}"


def extract_text_from_file(uploaded_file) -> str:
    """
    Best-effort extraction of text from the uploaded file.

    For PDFs we try PyPDF2 if available.
    For TXT / MD / CSV we decode as UTF-8.
    For DOCX we try python-docx if available.

    If extraction fails, we return an empty string and the user can
    paste text manually.
    """
    if uploaded_file is None:
        return ""

    filename = uploaded_file.name or ""
    ext = filename.lower().rsplit(".", 1)[-1]

    raw_bytes = uploaded_file.read()
    uploaded_file.seek(0)  # reset for any future reads

    # Simple text-based types
    if ext in {"txt", "md", "markdown", "csv"}:
        try:
            return raw_bytes.decode("utf-8", errors="ignore")
        except Exception:
            st.warning("Could not decode the file as UTF-8 text. Please paste the text manually on the right.")
            return ""

    # PDF
    if ext == "pdf":
        try:
            try:
                import PyPDF2  # type: ignore
            except ImportError:
                st.warning("PDF support requires PyPDF2. Please paste text manually, or ask your developer to add PyPDF2.")
                return ""

            reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n\n".join(pages).strip()
        except Exception as exc:
            st.warning(f"Could not extract text from PDF ({exc}). Please paste the text manually.")
            return ""

    # DOCX
    if ext == "docx":
        try:
            try:
                import docx  # type: ignore
            except ImportError:
                st.warning("DOCX support requires python-docx. Please paste text manually, or ask your developer to add it.")
                return ""

            document = docx.Document(io.BytesIO(raw_bytes))
            paragraphs = [p.text for p in document.paragraphs]
            return "\n\n".join(paragraphs).strip()
        except Exception as exc:
            st.warning(f"Could not extract text from DOCX ({exc}). Please paste the text manually.")
            return ""

    st.warning(f"File type '.{ext}' is not supported for automatic text extraction. Please paste text manually.")
    return ""


def generate_summary(email: str, text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Call the backend /summarize endpoint with the given text.

    Returns:
        (summary_text, error_message)
    """
    if not text.strip():
        return None, "No input text provided."

    payload = {
        "email": email or "",
        "text": text,
        # Let backend know which plan we think the user is on, if available.
        "plan": st.session_state.get("subscription_plan", "free"),
    }

    try:
        resp = requests.post(
            f"{BACKEND_URL}/summarize",
            json=payload,
            timeout=120,
        )
        if resp.status_code != 200:
            return None, f"Backend returned {resp.status_code}: {resp.text}"

        data = resp.json()
        summary = data.get("summary") or data.get("summary_text")
        if not summary:
            return None, "Backend did not return a summary."
        return summary, None
    except Exception as exc:
        return None, f"Unable to reach backend: {exc}"


def render_plan_status(plan: str, error: Optional[str]) -> None:
    """Render the subscription status + guidance text."""
    plan_label_map = {
        "free": "Free plan",
        "basic": "Basic plan",
        "pro": "Pro plan",
        "enterprise": "Enterprise plan",
    }
    label = plan_label_map.get(plan, "Free plan")

    st.write("**Status:**", label)

    if error:
        st.warning(
            "We couldn’t verify your subscription just now, so we’re treating you as on the "
            "free plan for this session.\n\n"
            f"Technical details: {error}"
        )
    else:
        if plan == "free":
            st.info(
                "You’re on the **Free plan**. Summaries are shorter and upload limits are lower. "
                "Upgrade on the Billing page for higher limits and deeper analysis."
            )
        elif plan == "basic":
            st.success(
                "You’re on the **Basic plan**. You can upload up to 5 documents per month for richer summaries."
            )
        elif plan == "pro":
            st.success(
                "You’re on the **Pro plan**. You can upload up to 30 documents per month for deeper, "
                "more structured summaries."
            )
        else:  # enterprise
            st.success(
                "You’re on the **Enterprise plan** with unlimited uploads and team features."
            )


# ---------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------

st.set_page_config(page_title="Upload Data – AI Report", page_icon="📄", layout="wide")

st.title("Upload Data & Generate a Business-Friendly Summary")
st.caption(
    "Turn dense reports, meeting notes, and long documents into a clear, client-ready summary "
    "you can drop into emails, slide decks, or status updates."
)

st.markdown("---")

# ---------------------------------------------------------------------
# Email + subscription section
# ---------------------------------------------------------------------

st.subheader("Your email")
st.caption("Use the same email address you subscribed with on the Billing page.")

if "user_email" not in st.session_state:
    st.session_state["user_email"] = ""
if "subscription_plan" not in st.session_state:
    st.session_state["subscription_plan"] = "free"
if "subscription_error" not in st.session_state:
    st.session_state["subscription_error"] = None

email = st.text_input("Email address", value=st.session_state["user_email"])

col_email_btn, _ = st.columns([1, 3])
with col_email_btn:
    if st.button("Save email & check plan", type="primary"):
        st.session_state["user_email"] = email.strip()
        if email.strip():
            plan, err = get_subscription_status(email.strip())
            st.session_state["subscription_plan"] = plan
            st.session_state["subscription_error"] = err
        else:
            st.session_state["subscription_plan"] = "free"
            st.session_state["subscription_error"] = "Please enter an email address."

# Show current status
render_plan_status(
    st.session_state.get("subscription_plan", "free"),
    st.session_state.get("subscription_error"),
)

st.markdown("---")

# ---------------------------------------------------------------------
# 1. Add your content
# ---------------------------------------------------------------------

st.subheader("1. Add your content")

left, right = st.columns(2)

with left:
    st.markdown("#### Upload a file")
    st.caption("Supported formats: TXT, MD, MARKDOWN, PDF, DOCX, CSV (max 200MB per file).")

    uploaded_file = st.file_uploader(
        "Drag and drop file here",
        type=["txt", "md", "markdown", "pdf", "docx", "csv"],
        help="Upload a report, memo, or other business document.",
    )

with right:
    st.markdown("#### Or paste text manually")
    manual_text = st.text_area(
        "Paste meeting notes, reports, or any free-text content.",
        height=260,
    )

input_text = ""

if uploaded_file is not None:
    file_text = extract_text_from_file(uploaded_file)
    if file_text:
        input_text = file_text

if manual_text.strip():
    # If both are present, append manual notes after uploaded text
    if input_text:
        input_text = input_text + "\n\n" + manual_text.strip()
    else:
        input_text = manual_text.strip()

# ---------------------------------------------------------------------
# 2. Generate a summary
# ---------------------------------------------------------------------

st.markdown("---")
st.subheader("2. Generate a summary")

char_count = len(input_text)
st.caption(f"Detected ~{char_count:,} characters in your input.")

generate_col, _ = st.columns([1, 3])

summary_placeholder = st.empty()
status_placeholder = st.empty()

with generate_col:
    generate_clicked = st.button("Generate Business Summary", type="primary")

if generate_clicked:
    if not input_text.strip():
        status_placeholder.error("Please upload a file or paste some text before generating a summary.")
    else:
        status_placeholder.info("Generating summary… This may take a moment.")
        summary, error = generate_summary(st.session_state.get("user_email", ""), input_text)
        if error:
            status_placeholder.error(f"Summarization failed. Details: {error}")
        else:
            status_placeholder.success("Summary generated successfully.")
            summary_placeholder.markdown("### Summary for your client or audience")
            summary_placeholder.markdown(summary)

# ---------------------------------------------------------------------
# 3. Explainer
# ---------------------------------------------------------------------

st.markdown("---")
st.subheader("What this tool does for you")

st.markdown(
    """
- **Saves time** – Turn dense reports and notes into short, readable summaries.  
- **Improves clarity** – Highlight key points, risks, decisions, and next steps.  
- **Helps communication** – Quickly share updates with clients, managers, or your team.
"""
)
