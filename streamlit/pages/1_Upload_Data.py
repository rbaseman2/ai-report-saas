import streamlit as st
import requests
from io import BytesIO
import os



# ---------- Config ----------
st.set_page_config(page_title="Upload Data – AI Report")

BACKEND_URL = os.getenv("BACKEND_URL")

if not BACKEND_URL:
    st.error(
        "BACKEND_URL is not configured in your Streamlit secrets. "
        "Add it under `.streamlit/secrets.toml` and redeploy."
    )
    st.stop()

st.title("Upload Data & Generate a Business-Friendly Summary")
st.caption(
    "Turn dense reports, meeting notes, and long documents into a clear, "
    "client-ready summary you can drop into emails, slide decks, or status updates."
)

# ============================================================
# Helpers
# ============================================================

def check_subscription(email: str):
    """
    Call the backend to get the current subscription for this email.
    Expected API: POST /subscription-status  { email: str }

    Returns:
        dict with at least {"plan": "free" | "basic" | "pro" | "enterprise"}
        or None if the backend is unreachable / error.
    """
    if not email:
        return None

    try:
        resp = requests.post(
            f"{BACKEND_URL}/subscription-status",
            json={"email": email},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        # 404 or anything else => treat as no subscription (free)
        return {"plan": "free"}
    except Exception:
        return None


def extract_text_from_file(uploaded_file) -> str:
    """
    Extract text from supported file types.
    Supported: .txt, .md, .pdf, .docx, .csv (basic text join)
    """
    filename = uploaded_file.name.lower()

    # Plain text / markdown
    if filename.endswith(".txt") or filename.endswith(".md"):
        return uploaded_file.read().decode("utf-8", errors="ignore")

    # Simple CSV -> just join lines as text
    if filename.endswith(".csv"):
        return uploaded_file.read().decode("utf-8", errors="ignore")

    # PDF
    if filename.endswith(".pdf"):
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            st.error("PDF support requires PyPDF2 to be installed on the backend environment.")
            return ""
        reader = PdfReader(uploaded_file)
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return "\n\n".join(pages)

    # DOCX
    if filename.endswith(".docx"):
        try:
            import docx  # python-docx
        except ImportError:
            st.error("DOCX support requires python-docx to be installed on the backend environment.")
            return ""
        doc = docx.Document(uploaded_file)
        return "\n".join(p.text for p in doc.paragraphs)

    st.error("Unsupported file type. Please upload TXT, MD, PDF, DOCX, or CSV.")
    return ""


def call_summarize_api(email: str, text: str, title: str):
    """
    Call the backend /summarize endpoint.

    We keep the payload very generic so it stays compatible with your existing FastAPI code.
    """
    payload = {
        "email": email,
        "title": title,
        "text": text,
    }

    resp = requests.post(
        f"{BACKEND_URL}/summarize",
        json=payload,
        timeout=120,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Backend returned {resp.status_code}: {resp.text}")

    # Try JSON first, fall back to raw text
    try:
        data = resp.json()
        return (
            data.get("summary")
            or data.get("business_summary")
            or data.get("patient_summary")
            or resp.text
        )
    except ValueError:
        return resp.text


# ============================================================
# 1. Email + Subscription Status
# ============================================================

st.subheader("Your email")

# Prefer the email saved on the Billing page if we have it
default_email = st.session_state.get("user_email", "")
email = st.text_input(
    "Use the same email you subscribed with.",
    value=default_email,
    placeholder="you@example.com",
)

if email and email != default_email:
    # Keep session in sync
    st.session_state["user_email"] = email

status_placeholder = st.empty()
sub_info = None

if email:
    sub_info = check_subscription(email)

    if not sub_info:
        status_placeholder.warning(
            "We couldn't verify your subscription just now, "
            "so we're treating you as on the **Free plan** for this session."
        )
        plan_label = "free"
    else:
        plan_label = sub_info.get("plan", "free")

    if plan_label == "free":
        status_placeholder.info(
            "Status: **Free plan**. Summaries are shorter and input size is limited. "
            "Upgrade on the **Billing** page for higher limits and deeper analysis."
        )
    elif plan_label == "basic":
        status_placeholder.success(
            "Status: **Basic plan** – up to 5 documents per month with full-length summaries."
        )
    elif plan_label == "pro":
        status_placeholder.success(
            "Status: **Pro plan** – up to 30 documents per month with richer analysis."
        )
    elif plan_label == "enterprise":
        status_placeholder.success(
            "Status: **Enterprise plan** – unlimited uploads for your team."
        )
    else:
        status_placeholder.info(f"Status: **{plan_label}** plan.")
else:
    status_placeholder.warning("Enter your email above to check your plan and limits.")

st.markdown("---")

# ============================================================
# 2. Upload / Paste content
# ============================================================

st.subheader("1. Add your content")

left_col, right_col = st.columns(2)

with left_col:
    st.markdown("#### Upload a file")
    st.caption("Supported formats: TXT, MD, PDF, DOCX, CSV (max 200MB per file).")

    uploaded_file = st.file_uploader(
        "Drag and drop a file here",
        type=["txt", "md", "pdf", "docx", "csv"],
        label_visibility="collapsed",
    )

with right_col:
    st.markdown("#### Or paste text manually")
    manual_text = st.text_area(
        "Paste meeting notes, reports, or any free-text content.",
        height=260,
    )

# Combine text from file + manual paste
combined_text = ""

if uploaded_file:
    file_text = extract_text_from_file(uploaded_file)
    combined_text += file_text

if manual_text:
    if combined_text:
        combined_text += "\n\n" + manual_text
    else:
        combined_text = manual_text

char_count = len(combined_text)
st.caption(f"Detected **{char_count:,}** characters in total from your upload and pasted text.")

st.markdown("---")

# ============================================================
# 3. Generate summary
# ============================================================

st.subheader("2. Generate a summary")

if not email:
    st.warning("Please enter your email above before generating a summary.")
    can_generate = False
else:
    can_generate = True

generate = st.button("Generate Business Summary", disabled=not can_generate)

summary_placeholder = st.empty()

if generate:
    if not combined_text.strip():
        summary_placeholder.error("Please upload a file or paste some text before generating a summary.")
    else:
        with st.spinner("Generating your business-friendly summary…"):
            try:
                title = uploaded_file.name if uploaded_file else "Uploaded content"
                summary_text = call_summarize_api(email=email, text=combined_text, title=title)
            except Exception as e:
                summary_placeholder.error(f"Summarization failed: {e}")
            else:
                st.subheader("Summary for your client or audience")
                st.markdown(summary_text)
                st.success("Summary generated successfully.")
