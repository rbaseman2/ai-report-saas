# streamlit/pages/1_Upload_Data.py

import os
import io
import csv
import requests
import streamlit as st

# Page config MUST be first Streamlit command
st.set_page_config(page_title="Upload Data – AI Report", page_icon="📄")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

# ------------------------------------------------------------
# Shared helpers (match Billing page)
# ------------------------------------------------------------

def check_subscription_status(email: str):
    default = {
        "plan": "free",
        "max_documents": 5,
        "max_chars": 200_000,
        "status": "default",
    }

    if not BACKEND_URL:
        return {**default, "status": "backend_url_missing"}

    if not email:
        return default

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
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


def summarize_document(email: str, text: str, filename: str, plan: str):
    """
    Call the backend /summarize endpoint.
    """
    if not BACKEND_URL:
        st.error("Backend URL is not configured.")
        return None

    try:
        resp = requests.post(
            f"{BACKEND_URL}/summarize",
            json={
                "email": email,
                "text": text,
                "filename": filename,
                "plan": plan,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text
        st.error(f"Backend error: {detail or e}")
    except Exception as e:
        st.error(f"Error calling summarization backend: {e}")

    return None

# ------------------------------------------------------------
# Page UI
# ------------------------------------------------------------

st.title("Upload Data & Generate a Business-Friendly Summary")

if not BACKEND_URL:
    st.error("Backend URL is not configured in this environment.")
    st.stop()

# Email – shared with Billing via session_state
st.markdown("### Your email")
default_email = st.session_state.get("user_email", "")
email = st.text_input(
    "Use the same email address you subscribed with on the Billing page.",
    value=default_email,
    placeholder="you@company.com",
)

if email and email != default_email:
    st.session_state["user_email"] = email

sub = check_subscription_status(email) if email else None
plan_label = (sub["plan"].capitalize() if sub else "Free")

with st.container(border=True):
    if not email:
        st.markdown("**Status:** Free plan.")
        st.caption(
            "Enter your email to unlock higher limits if you have a paid subscription."
        )
    else:
        st.markdown(f"**Status:** {plan_label} plan.")
        st.caption(
            f"You can upload up to **{sub['max_documents']}** documents "
            f"and about **{sub['max_chars']:,}** characters in total each month."
        )
        if sub["status"] == "no_subscription":
            st.info(
                "We didn’t find an active subscription for this email, "
                "so we’re treating you as on the Free plan."
            )
        elif sub["status"] == "error":
            st.warning(
                "We couldn’t reach the billing system. "
                "For now, we’re treating you as on the Free plan."
            )

st.divider()

# ------------------------------------------------------------
# Upload section
# ------------------------------------------------------------

st.markdown("### 1. Add your content")

uploaded_file = st.file_uploader(
    "Upload a report file (TXT, MD, PDF, DOCX, CSV).",
    type=["txt", "md", "pdf", "docx", "csv"],
)

manual_text = st.text_area(
    "Or paste text manually",
    placeholder="Paste meeting notes, reports, or any free-text content...",
    height=200,
)

st.markdown("### 2. Generate a summary")

if st.button("Generate Business Summary"):
    if not email:
        st.error("Please enter your email address first.")
    else:
        # Decide source of text
        if uploaded_file is None and not manual_text.strip():
            st.error("Upload a file or paste some text to summarize.")
        else:
            if manual_text.strip():
                text = manual_text.strip()
                filename = "pasted_text.txt"
            else:
                filename = uploaded_file.name
                # Simple handling: for now treat everything as text-ish;
                # your backend can do more sophisticated parsing.
                try:
                    content = uploaded_file.read()
                    text = content.decode("utf-8", errors="ignore")
                except Exception as e:
                    st.error(f"Could not read uploaded file: {e}")
                    st.stop()

            if len(text) > (sub["max_chars"] if sub else 200_000):
                st.warning(
                    "This document is quite large for your current plan. "
                    "The summary may be truncated."
                )

            with st.spinner("Generating your summary…"):
                result = summarize_document(email, text, filename, sub["plan"] if sub else "free")

            if result:
                st.markdown("### Summary")
                st.write(result.get("summary", ""))

                bullets = result.get("key_points")
                if bullets:
                    st.markdown("### Key points")
                    for b in bullets:
                        st.markdown(f"- {b}")

                risks = result.get("risks")
                if risks:
                    st.markdown("### Risks & issues")
                    for r in risks:
                        st.markdown(f"- {r}")

                actions = result.get("actions")
                if actions:
                    st.markdown("### Recommended next steps")
                    for a in actions:
                        st.markdown(f"- {a}")
