import os
import io
import requests
import streamlit as st
from PyPDF2 import PdfReader

# ---------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Upload Data – AI Report",
    page_icon="📄",
    layout="wide",
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def get_backend_url() -> str:
    """Return backend URL (for debugging, also show on Billing page)."""
    return BACKEND_URL.rstrip("/")


def get_subscription(email: str) -> dict:
    """
    Ask the backend which plan this email is on.
    Falls back to 'free' if anything goes wrong.
    Expected backend response (example):

      {
        "email": "user@example.com",
        "plan": "basic",          # 'free' | 'basic' | 'pro' | 'enterprise'
        "label": "Basic plan",
        "max_docs": 5,
        "max_chars": 20000
      }
    """
    if not email:
        return {"plan": "free", "label": "Free plan"}

    try:
        resp = requests.get(
            f"{get_backend_url()}/subscription/status",
            params={"email": email},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            if "plan" not in data:
                data["plan"] = "free"
            if "label" not in data:
                data["label"] = data["plan"].capitalize() + " plan"
            return data
        else:
            st.warning(
                "We couldn’t verify your subscription just now, "
                "so we’re treating you as on the free plan for this session."
            )
    except Exception:
        st.warning(
            "We couldn’t reach the subscription server, "
            "so we’re treating you as on the free plan for this session."
        )

    return {"plan": "free", "label": "Free plan"}


def read_file_to_text(uploaded_file) -> str:
    """
    Convert an uploaded file to plain text.
    Supports .txt, .md, .csv and .pdf (simple PDF extraction).
    """
    if uploaded_file is None:
        return ""

    name = uploaded_file.name.lower()
    content = uploaded_file.read()

    # Reset stream for later re-use by Streamlit if needed
    uploaded_file.seek(0)

    if name.endswith(".txt") or name.endswith(".md") or name.endswith(".csv"):
        try:
            return content.decode("utf-8", errors="ignore")
        except Exception:
            return content.decode("latin-1", errors="ignore")

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pass
        return "\n\n".join(pages)

    # Fallback: try to treat as text
    try:
        return content.decode("utf-8", errors="ignore")
    except Exception:
        return content.decode("latin-1", errors="ignore")


def call_summarizer_api(email: str, text: str, plan: str) -> dict:
    """
    Call the FastAPI backend /summarize endpoint.
    """
    payload = {
        "email": email,
        "plan": plan,
        "text": text,
    }

    resp = requests.post(
        f"{get_backend_url()}/summarize",
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------

st.title("Upload Data & Generate a Business-Friendly Summary")

st.caption(
    "Turn dense reports, meeting notes, and long documents into a clear, "
    "client-ready summary you can drop into emails, slide decks, or status updates."
)

# ----------------------------- EMAIL / PLAN ---------------------------

st.markdown("### Your email")

default_email = st.session_state.get("user_email", "")
email = st.text_input(
    "Use the same email address you subscribed with on the Billing page.",
    value=default_email,
    placeholder="you@example.com",
)

if email:
    st.session_state["user_email"] = email

sub_info = get_subscription(email)
plan = sub_info.get("plan", "free")
plan_label = sub_info.get("label", "Free plan")

# Human-friendly explanation per plan
if plan == "free":
    plan_explainer = (
        "You’re on the **Free plan**. Summaries are shorter and upload limits are lower. "
        "Upgrade on the **Billing** page for higher limits and deeper analysis."
    )
elif plan == "basic":
    plan_explainer = (
        "You’re on the **Basic plan**. You can upload up to **5 documents per month** "
        "for rich, business-friendly summaries."
    )
elif plan == "pro":
    plan_explainer = (
        "You’re on the **Pro plan**. You can upload up to **30 documents per month** "
        "with deeper structure, key risks, and action items."
    )
else:  # enterprise
    plan_explainer = (
        "You’re on the **Enterprise plan**. You have **unlimited uploads** for your team, "
        "plus the most detailed summaries."
    )

st.markdown(
    f"**Status:** {plan_label}  \n"
    f"{plan_explainer}"
)

st.divider()

# ----------------------------- CONTENT INPUT -------------------------

st.markdown("### 1. Add your content")

col_left, col_right = st.columns([1.2, 1])

with col_left:
    st.subheader("Upload a file", anchor=False)
    st.caption(
        "Supported formats: TXT, MD, PDF, DOCX, CSV (max 200MB per file)."
    )

    uploaded_file = st.file_uploader(
        "Drag and drop a file here",
        type=["txt", "md", "markdown", "pdf", "docx", "csv"],
        label_visibility="collapsed",
    )

with col_right:
    st.subheader("Or paste text manually", anchor=False)
    manual_text = st.text_area(
        "Paste meeting notes, reports, or any free-text content.",
        height=260,
        label_visibility="collapsed",
    )

# ----------------------------- SUMMARY ACTION ------------------------

st.markdown("### 2. Generate a summary")

# Decide which text we’ll send
source_text = ""
source_label = ""

if manual_text.strip():
    source_text = manual_text.strip()
    source_label = "pasted text"
elif uploaded_file is not None:
    source_text = read_file_to_text(uploaded_file)
    source_label = f"file: {uploaded_file.name}"

if source_text:
    char_count = len(source_text)
    st.caption(f"Detected ~{char_count:,} characters in your {source_label}.")
else:
    st.caption("Upload a file or paste text on the right to get started.")

# Button to generate
generate_clicked = st.button("Generate Business Summary", type="primary")

summary_container = st.empty()

if generate_clicked:
    if not email:
        st.error("Please enter your email first so we can apply the correct plan limits.")
    elif not source_text:
        st.error("Please upload a file or paste some text before generating a summary.")
    else:
        with st.spinner("Thinking through your content and generating a summary…"):
            try:
                result = call_summarizer_api(email=email, text=source_text, plan=plan)
                summary_text = result.get("summary", "").strip()

                if not summary_text:
                    summary_container.warning(
                        "No summary was returned. You may want to try with a shorter input "
                        "or check your API configuration in the backend."
                    )
                else:
                    st.session_state["last_summary"] = summary_text
                    summary_container.success("Summary generated successfully.")
            except requests.exceptions.HTTPError as e:
                summary_container.error(
                    f"Summarization failed. Details: {e.response.status_code} "
                    f"{e.response.reason}"
                )
            except requests.exceptions.RequestException as e:
                summary_container.error(f"Summarization failed. Details: {e}")
            except Exception as e:
                summary_container.error(f"Unexpected error while summarizing: {e}")

# ----------------------------- SUMMARY DISPLAY -----------------------

st.markdown("### Summary for your client or audience")

final_summary = st.session_state.get("last_summary", "").strip()
if final_summary:
    st.markdown(final_summary)
else:
    st.info(
        "Your summary will appear here. Upload content and click "
        "**Generate Business Summary** to get started."
    )

st.divider()

# ----------------------------- VALUE PROP ----------------------------

st.markdown("### What this tool does for you")

st.markdown(
    """
- **Saves time** – Turn dense reports and notes into short, readable summaries.
- **Improves clarity** – Highlight key points, risks, decisions, and next steps.
- **Helps communication** – Quickly share updates with clients, managers, or your team.
"""
)
