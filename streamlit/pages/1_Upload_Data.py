import os
import io
import requests
import streamlit as st
from PyPDF2 import PdfReader

# Must be first Streamlit command on the page
st.set_page_config(
    page_title="Upload Data – AI Report",
    page_icon="📄",
    layout="wide",
)

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")


# ---------------------- HELPERS ---------------------- #

def extract_text_from_pdf(file) -> str:
    """Extract text from a PDF file-like object."""
    try:
        reader = PdfReader(file)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    except Exception:
        return ""


def extract_text_from_file(uploaded_file) -> str:
    """Handle txt, md, pdf, csv uniformly as plain text."""
    if uploaded_file is None:
        return ""

    filename = uploaded_file.name.lower()

    if filename.endswith(".pdf"):
        return extract_text_from_pdf(uploaded_file)

    try:
        raw = uploaded_file.read()
        try:
            return raw.decode("utf-8")
        except Exception:
            return raw.decode("latin-1", errors="ignore")
    finally:
        uploaded_file.seek(0)


def get_subscription_status(email: str) -> dict:
    if not BACKEND_URL or not email:
        return {"plan": "free", "active": False}

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"plan": "free", "active": False}


def summarize(email: str, text: str) -> dict:
    """Call backend /summarize endpoint."""
    if not BACKEND_URL:
        return {"error": "Backend URL is not configured."}

    payload = {"email": email, "text": text}
    resp = requests.post(f"{BACKEND_URL}/summarize", json=payload, timeout=60)
    if resp.status_code != 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        msg = data.get("detail") or f"Backend error ({resp.status_code})"
        return {"error": msg}
    return resp.json()


# ---------------------- UI ---------------------- #

st.title("Upload Data & Generate a Client-Ready Summary")

st.subheader("Your email")
st.caption("Use the same email address you used (or will use) on the Billing page.")
email = st.text_input("Email", placeholder="you@example.com")

status_info = get_subscription_status(email) if email else {"plan": "free", "active": False}
plan = status_info.get("plan", "free")
active = status_info.get("active", False)

status_label = f"{plan.capitalize()} (active)" if active else "Free"
st.write(f"**Status:** {status_label}")

if not active:
    st.info(
        "You’re currently on the **Free** tier. Summaries may be shorter and input size "
        "may be limited. Upgrade on the **Billing** page for higher limits and richer summaries."
    )

st.markdown("---")

# ---------------------- STEP 1: ADD CONTENT ---------------------- #

st.subheader("1. Add your content")
st.caption(
    "Upload reports, meeting notes, proposals, research, or any long-form document you "
    "want turned into a clear summary for clients or stakeholders."
)

left, right = st.columns([1.4, 1])

with left:
    st.write("**Upload documents**")
    uploaded_file = st.file_uploader(
        "Drag and drop a file here",
        type=["txt", "md", "pdf", "csv"],
        help="Supported formats: TXT, MD, PDF, CSV (up to 200MB per file).",
    )

with right:
    st.write("**…or paste text manually**")
    pasted_text = st.text_area(
        "Paste any text you want summarized:",
        height=220,
        placeholder="Paste email threads, call notes, draft documents, or research here…",
        label_visibility="collapsed",
    )

# Decide which text to use
text_from_file = extract_text_from_file(uploaded_file) if uploaded_file else ""
final_text = pasted_text.strip() or text_from_file.strip()

char_count = len(final_text)
if char_count:
    st.caption(f"Detected about **{char_count:,}** characters of input.")
else:
    st.caption("No content detected yet. Upload a file or paste text to continue.")

st.markdown("---")

# ---------------------- STEP 2: GENERATE SUMMARY ---------------------- #

st.subheader("2. Generate a summary")

generate_button = st.button("Generate Client-Ready Summary", type="primary", disabled=not final_text or not email)

if not email:
    st.warning("Enter your email before generating a summary.", icon="⚠️")

if generate_button and final_text and email:
    with st.spinner("Generating summary…"):
        result = summarize(email=email, text=final_text)

    if "error" in result:
        st.error(f"Summary generation failed: {result['error']}")
    else:
        summary_text = result.get("summary", "").strip()

        st.subheader("Summary for your client or audience")
        st.caption(
            "Use this in emails, reports, slide decks, or internal updates. "
            "It’s written for non-technical readers."
        )

        if summary_text:
            st.write(summary_text)
        else:
            st.warning("No summary was returned by the backend. Try adjusting the input text.")
