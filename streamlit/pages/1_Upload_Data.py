import os
import textwrap
import requests
import streamlit as st

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    BACKEND_URL = "https://ai-report-backend-ubrx.onrender.com"  # <-- keep or update to your backend

st.set_page_config(page_title="Upload Data – AI Report", page_icon="📄")

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def check_subscription(email: str):
    """
    Ask the backend for this email's subscription status.
    Falls back to Free plan if anything goes wrong.
    """
    default_limits = {
        "max_documents": 5,
        "max_chars": 200_000,
    }

    if not email:
        return "free", default_limits, "Enter your email to check your subscription."

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=20,
        )

        # 404 from backend means "no active subscription"
        if resp.status_code == 404:
            return "free", default_limits, "No active subscription found – using Free plan for this session."

        resp.raise_for_status()
        data = resp.json()

        plan = data.get("plan", "free")
        limits = {
            "max_documents": data.get("max_documents", default_limits["max_documents"]),
            "max_chars": data.get("max_chars", default_limits["max_chars"]),
        }
        return plan, limits, ""
    except Exception as e:
        return "free", default_limits, f"Error while checking subscription: {e}"


def summarize_document(email: str, text: str, filename: str | None, plan: str):
    """
    Call the backend /summarize endpoint.
    Backend expects JSON with: email, text, filename, plan
    """
    payload = {
        "email": email,
        "text": text,
        "filename": filename,
        "plan": plan,
    }

    try:
        resp = requests.post(
            f"{BACKEND_URL}/summarize",
            json=payload,
            timeout=120,
        )

        if resp.status_code != 200:
            # Try to surface useful error info from FastAPI
            try:
                data = resp.json()
            except Exception:
                data = resp.text
            st.error(f"Backend error: {data}")
            return None

        return resp.json()
    except Exception as e:
        st.error(f"Summarization failed: {e}")
        return None


# -------------------------------------------------------------------
# Page UI
# -------------------------------------------------------------------
st.title("Upload Data & Generate a Business-Friendly Summary")

st.write(
    "Turn dense reports or long documents into a clear, client-ready summary you can "
    "drop into emails, slide decks, or status updates."
)

# -------------------------------------------------------------------
# 1. Email + Plan status
# -------------------------------------------------------------------
st.subheader("Your email")

default_email = st.session_state.get("billing_email", "")
email = st.text_input(
    "Use the same email address you subscribed with on the Billing page.",
    value=default_email,
    placeholder="you@example.com",
)

# Keep email in session so Billing and Upload pages stay in sync
if email:
    st.session_state["billing_email"] = email

plan, limits, status_msg = check_subscription(email)

status_text = f"Status: **{plan.capitalize()} plan**"
if status_msg:
    st.info(f"{status_text}. {status_msg}")
else:
    st.success(
        f"{status_text}. You can upload up to "
        f"{limits['max_documents']} documents and about "
        f"{limits['max_chars']:,} characters in total each month."
    )

st.markdown("---")

# -------------------------------------------------------------------
# 2. Add your content
# -------------------------------------------------------------------
st.subheader("1. Add your content")

uploaded_file = st.file_uploader(
    "Upload a report file (TXT, MD, PDF, DOCX, CSV).",
    type=["txt", "md", "pdf", "docx", "csv"],
)

manual_text = st.text_area(
    "Or paste text manually",
    placeholder="Paste meeting notes, reports, or any free-text content...",
    height=220,
)

st.markdown("---")

# -------------------------------------------------------------------
# 3. Generate a summary
# -------------------------------------------------------------------
st.subheader("2. Generate a summary")

if st.button("Generate Business Summary", type="primary"):
    # --- Basic validation ---
    if not email:
        st.error("Please enter the same email you used on the Billing page before generating a summary.")
        st.stop()

    # Collect text from upload or manual input
    full_text = ""
    filename = None

    if uploaded_file is not None:
        filename = uploaded_file.name
        try:
            # Simple binary -> text decode; your backend still does chunking & cleaning
            uploaded_bytes = uploaded_file.read()
            full_text = uploaded_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            st.error(f"Could not read uploaded file: {e}")
            st.stop()

    if manual_text.strip():
        # If both file and manual text are provided, concatenate them
        if full_text:
            full_text += "\n\n" + manual_text.strip()
        else:
            full_text = manual_text.strip()

    if not full_text:
        st.error("Please upload a file or paste some text before generating a summary.")
        st.stop()

    # --- Call backend ---
    with st.spinner("Talking to the AI engine…"):
        result = summarize_document(email=email, text=full_text, filename=filename, plan=plan)

    if result is not None:
        summary = result.get("summary") or result.get("summary_text") or ""

        if not summary:
            st.warning("Backend responded, but no summary text was found in the response.")
        else:
            st.subheader("Generated business summary")
            st.write(summary)

            # Optional: show some metadata if backend returns it
            meta = {k: v for k, v in result.items() if k not in {"summary", "summary_text"}}
            if meta:
                with st.expander("Technical details (from backend)"):
                    st.json(meta)
