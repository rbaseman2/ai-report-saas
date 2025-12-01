# streamlit/pages/1_Upload_Data.py

import os
import io
import requests
import streamlit as st

# ❗ MUST be the first Streamlit command on this page
st.set_page_config(page_title="Upload Data", page_icon="📄")

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _get_backend_url() -> str:
    """
    Resolve the backend URL from Streamlit secrets or environment.
    """
    for key in ("BACKEND_URL", "backend_url", "backendUrl"):
        try:
            if key in st.secrets:
                return str(st.secrets[key]).rstrip("/")
        except Exception:
            pass

    return os.getenv("BACKEND_URL", "").rstrip("/")


def check_subscription_status(email: str, backend_url: str):
    """
    Ask the backend for the current subscription status for this email.
    Returns a dict with: plan, max_documents, max_chars, and a status flag.
    """
    default = {
        "plan": "free",
        "max_documents": 5,
        "max_chars": 200_000,
        "status": "default",
    }

    if not backend_url:
        return {**default, "status": "backend_url_missing"}

    if not email:
        return default

    try:
        resp = requests.get(
            f"{backend_url}/subscription-status",
            params={"email": email},
            timeout=10,
        )
        if resp.status_code == 404:
            return {**default, "status": "no_subscription"}

        resp.raise_for_status()
        data = resp.json()

        return {
            "plan": data.get("plan", "free"),
            "max_documents": data.get("max_documents", 5),
            "max_chars": data.get("max_chars", 200_000),
            "status": "ok",
        }
    except Exception:
        return {**default, "status": "error"}


def call_summarize_api(email: str, uploaded_file, backend_url: str):
    """
    Send the uploaded file + email to the backend /summarize endpoint.
    """
    if not backend_url:
        raise RuntimeError("Backend URL is not configured.")

    file_bytes = uploaded_file.read()
    file_bytes_io = io.BytesIO(file_bytes)

    files = {
        "file": (
            uploaded_file.name,
            file_bytes_io,
            uploaded_file.type or "application/octet-stream",
        )
    }
    data = {
        "email": email,
        "summary_style": "client_friendly_business",
    }

    resp = requests.post(
        f"{backend_url}/summarize",
        files=files,
        data=data,
        timeout=120,
    )
    resp.raise_for_status()

    try:
        payload = resp.json()
    except ValueError:
        return {"summary": resp.text}

    summary = (
        payload.get("summary")
        or payload.get("summary_markdown")
        or payload.get("markdown")
        or payload.get("result")
    )

    meta = {
        k: v
        for k, v in payload.items()
        if k not in ("summary", "summary_markdown", "markdown", "result")
    }

    return {"summary": summary, "meta": meta}


# ------------------------------------------------------------
# Page layout
# ------------------------------------------------------------

BACKEND_URL = _get_backend_url()

st.title("Upload a report to summarize")

if not BACKEND_URL:
    st.error("Backend URL is not configured in this environment.")
    st.stop()

st.caption(
    "Upload a PDF or Word document and we’ll generate a concise, client-ready summary: "
    "key insights, risks, and recommended next steps."
)

# ------------------------------------------------------------
# Email & plan status
# ------------------------------------------------------------

default_email = st.session_state.get("user_email", "")
email = st.text_input(
    "Your email (used to match your subscription)",
    value=default_email,
    placeholder="you@company.com",
)

if email and email != default_email:
    st.session_state["user_email"] = email

if not email:
    st.info("Enter your email above to check your plan and usage limits.")
    st.stop()

sub = check_subscription_status(email, BACKEND_URL)

plan_label = sub["plan"].capitalize()
with st.container(border=True):
    st.subheader("Plan & usage")

    st.markdown(f"**Current plan:** {plan_label}")
    st.caption(
        f"You can process up to **{sub['max_documents']}** documents "
        f"and roughly **{sub['max_chars']:,}** characters per billing period."
    )

    if sub["plan"] == "free":
        st.warning(
            "You’re currently on the Free tier. You can still try the tool, "
            "but for heavier usage we recommend upgrading in the **Billing** tab."
        )
    elif sub["status"] in ("error", "backend_url_missing"):
        st.warning(
            "We couldn’t fully confirm your plan details. "
            "If you experience limits that don’t match your subscription, please contact support."
        )

# ------------------------------------------------------------
# File upload
# ------------------------------------------------------------

st.markdown("### 1. Upload your document")

uploaded_file = st.file_uploader(
    "Upload a PDF or Word document",
    type=["pdf", "docx", "doc"],
)

st.markdown("### 2. Choose how you want the summary framed")

summary_focus = st.selectbox(
    "Summary focus",
    [
        "Client-ready executive summary",
        "Internal team briefing",
        "Opportunity & risk overview",
    ],
)

summary_style_hint = {
    "Client-ready executive summary": "client_ready",
    "Internal team briefing": "internal_briefing",
    "Opportunity & risk overview": "opportunity_and_risk",
}[summary_focus]

# ------------------------------------------------------------
# Generate summary
# ------------------------------------------------------------

st.markdown("### 3. Generate summary")

if st.button("Generate summary"):
    if not uploaded_file:
        st.error("Please upload a document first.")
    else:
        with st.spinner("Analyzing your document and generating a summary…"):
            try:
                result = call_summarize_api(email, uploaded_file, BACKEND_URL)
            except requests.HTTPError as e:
                try:
                    err_payload = e.response.json()
                    msg = err_payload.get("detail") or err_payload
                except Exception:
                    msg = str(e)
                st.error(f"Backend returned an error: {msg}")
            except Exception as e:
                st.error(f"Unexpected error while summarizing: {e}")
            else:
                summary_text = result.get("summary")
                meta = result.get("meta", {}) or {}

                if not summary_text:
                    st.warning(
                        "The backend did not return a summary field. "
                        "Raw response may be available in the logs."
                    )
                else:
                    st.success("Summary generated successfully.")

                    st.subheader("Executive summary")
                    st.markdown(summary_text)

                    if meta:
                        with st.expander("Technical details & usage info (optional)"):
                            st.json(meta)

st.caption(
    "Tip: For the best results, upload reports that have a clear narrative: "
    "project updates, proposals, financial reviews, or client deliverables."
)
