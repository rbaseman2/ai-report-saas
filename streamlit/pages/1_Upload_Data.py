# streamlit/pages/1_Upload_Data.py

import os
import io
import requests
import streamlit as st

st.subheader("Your email")
email = st.text_input(
    "Use the same email you subscribed with.",
    value=st.session_state.get("user_email", ""),
    placeholder="you@example.com",
)
if email:
    st.session_state["user_email"] = email.strip().lower()


# IMPORTANT: Do NOT call st.set_page_config here.
# It should only be called once in Home.py / the main script.

st.markdown("### Upload Data & Generate a Patient-Friendly Summary")
st.caption(
    "Turn long consultation notes, intake forms, or reports into a clear, "
    "patient-facing summary in seconds."
)

# ---------------------------------------------------------------------
# Backend URL helper (same pattern as Billing page)
# ---------------------------------------------------------------------
def _get_backend_url() -> str:
    """
    Prefer BACKEND_URL env var (Render) and only fall back to
    st.secrets when running locally. Prevents red 'No secrets' banner on Render.
    """
    env_val = os.getenv("BACKEND_URL", "").rstrip("/")
    if env_val:
        return env_val

    try:
        return st.secrets["backend_url"].rstrip("/")
    except Exception:
        return ""
BACKEND_URL = _get_backend_url()

# ---------------------------------------------------------------------
# Entitlement check – call /me on the backend
# ---------------------------------------------------------------------
def _check_premium(email: str) -> bool:
    if not BACKEND_URL or not email.strip():
        return False
    try:
        r = requests.get(
            f"{BACKEND_URL}/me",
            params={"email": email.strip().lower()},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json() or {}
            return bool(data.get("has_active_subscription"))
    except Exception as e:
        st.warning(f"Could not verify subscription status: {e}")
    return False


is_premium = _check_premium(email)


status_col1, status_col2 = st.columns([1, 3])
with status_col1:
    st.markdown(
        f"**Status:** "
        + ("✅ <span style='color:#21c55d'>Premium</span>" if is_premium else "🆓 Free"),
        unsafe_allow_html=True,
    )
with status_col2:
    if is_premium:
        st.info(
            "You have full access. Upload larger files and generate richer summaries.",
            icon="✅",
        )
    else:
        st.info(
            "You’re on the free tier. Summaries are shorter and input size is limited. "
            "Upgrade on the **Billing** page for full access.",
            icon="ℹ️",
        )

# ---------------------------------------------------------------------
# File / text input
# ---------------------------------------------------------------------
st.divider()
st.subheader("1. Add your consultation content")

left, right = st.columns(2)

with left:
    uploaded_file = st.file_uploader(
        "Upload consultation notes or a report",
        type=["txt", "md", "pdf"],
        help="For best results, upload the full visit note or intake form.",
    )
    st.caption("You can also paste text directly into the box on the right.")

with right:
    default_placeholder = (
        "Paste consultation notes, HPI, assessment/plan, or any free-text report here..."
    )
    pasted_text = st.text_area(
        "Or paste text manually",
        value="",
        height=220,
        placeholder=default_placeholder,
    )

# ---------------------------------------------------------------------
# Read file contents if present
# ---------------------------------------------------------------------
def _read_file_text(file) -> str:
    if file is None:
        return ""

    name = (file.name or "").lower()
    if name.endswith((".txt", ".md")):
        try:
            raw = file.read()
            # Reset file pointer in case we read again later
            file.seek(0)
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    if name.endswith(".pdf"):
        # Try PyPDF2 – but don’t crash if it isn’t installed.
        try:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(io.BytesIO(file.read()))
            file.seek(0)
            text_chunks = []
            for page in reader.pages:
                try:
                    text_chunks.append(page.extract_text() or "")
                except Exception:
                    pass
            return "\n\n".join(text_chunks)
        except Exception:
            st.warning(
                "PDF support requires the `PyPDF2` package. "
                "Ask your developer to add it to `requirements.txt`, or upload a .txt file instead.",
                icon="⚠️",
            )
            return ""

    return ""


file_text = _read_file_text(uploaded_file)
combined_text = (file_text + "\n\n" + pasted_text).strip()

if not combined_text:
    st.warning("Upload a file or paste some text to get started.", icon="⬆️")

# ---------------------------------------------------------------------
# Summarizer call
# ---------------------------------------------------------------------
def _summarize_via_backend(text: str, max_sentences: int = 6):
    if not BACKEND_URL:
        st.error(
            "BACKEND_URL is not configured for the Streamlit service. "
            "Set it to your backend Render URL in the service environment."
        )
        return []

    try:
        payload = {
            "text": text,
            "max_sentences": max_sentences,
        }
        r = requests.post(
            f"{BACKEND_URL}/summarize",
            json=payload,
            timeout=30,
        )
        if r.status_code != 200:
            st.error(
                f"Summarization failed ({r.status_code}): "
                f"{getattr(r, 'text', '')[:400]}"
            )
            return []
        data = r.json() or {}
        return data.get("tldr") or []
    except Exception as e:
        st.error(f"Error contacting summarization service: {e}")
        return []


st.divider()
st.subheader("2. Generate a summary")

# Free vs premium limits
MAX_CHARS_FREE = 1500
MAX_SENTENCES_FREE = 4
MAX_SENTENCES_PREMIUM = 8

if not combined_text:
    st.caption("Once you add text, you’ll be able to generate a summary here.")
    st.stop()

text_len = len(combined_text)

if is_premium:
    st.caption(f"Detected ~{text_len} characters. Full summarization enabled ✅.")
else:
    if text_len > MAX_CHARS_FREE:
        st.warning(
            f"Free tier is limited to about {MAX_CHARS_FREE} characters. "
            f"We’ll summarize the first {MAX_CHARS_FREE:,} characters only. "
            "Upgrade to Premium for full-report summaries.",
            icon="⚠️",
        )
        combined_text = combined_text[:MAX_CHARS_FREE]
    else:
        st.caption(
            f"Detected ~{text_len} characters. Free-tier summary will be shorter. "
            "Upgrade for more detail."
        )

generate = st.button("Generate Patient-Friendly Summary", type="primary")

if generate:
    with st.spinner("Summarizing…"):
        max_sents = (
            MAX_SENTENCES_PREMIUM if is_premium else MAX_SENTENCES_FREE
        )
        bullets = _summarize_via_backend(combined_text, max_sentences=max_sents)

    st.subheader("Summary for the patient")
    if not bullets:
        st.error("No summary could be generated. Try adjusting the input text.")
    else:
        for b in bullets:
            st.markdown(f"- {b}")

        st.success(
            "Summary generated. You can copy/paste this into your patient portal, "
            "after-visit summary, or follow-up email.",
            icon="✅",
        )

    # Optional: a small “What you get with Premium” section
    st.divider()
    st.subheader("What this tool does for you")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("**⏱ Saves time**")
        st.caption("Turn dense clinical text into a patient-facing summary in seconds.")
    with col_b:
        st.markdown("**💬 Improves clarity**")
        st.caption("Highlights key concerns, next steps, and follow-up instructions.")
    with col_c:
        st.markdown("**📈 Scales with your practice**")
        st.caption("Premium tier lets you upload longer notes and generates richer reports.")

    if not is_premium:
        st.info(
            "Want longer, more detailed summaries and larger uploads? "
            "Go to the **Billing** page to upgrade to a paid plan.",
            icon="💳",
        )
