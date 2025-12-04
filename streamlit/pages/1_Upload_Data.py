# pages/1_Upload_Data.py

import os

import requests
import streamlit as st

st.set_page_config(page_title="Upload Data – AI Report", page_icon="📄")

# Again: only environment variable, no st.secrets
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.title("Upload Data & Generate a Business-Friendly Summary")
st.write(
    "Turn dense reports and meeting notes into a clear summary you can drop into emails, "
    "slide decks, or status updates."
)

# -------------------------------------------------------------------
# 1. Your email
# -------------------------------------------------------------------

st.subheader("Your email")

default_email = st.session_state.get("billing_email", "")
email = st.text_input(
    "Use the same email you subscribed with.",
    value=default_email,
    key="upload_email",
)

if email:
    st.session_state["billing_email"] = email

plan_info = None

if email:
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=15,
        )
        resp.raise_for_status()
        plan_info = resp.json()
    except Exception as e:
        st.warning(
            f"Couldn't contact the billing backend to get your plan. "
            f"Treating you as on the Free plan for now. ({e})"
        )

if plan_info is None:
    plan_info = {
        "plan": "free",
        "max_documents": 5,
        "max_chars": 200_000,
    }

with st.container(border=True):
    plan_name = plan_info.get("plan", "free").capitalize()
    max_docs = plan_info.get("max_documents", 5)
    max_chars = plan_info.get("max_chars", 200_000)
    st.write(f"Status: **{plan_name}** plan")
    st.write(
        f"You can upload up to **{max_docs} documents per month**, with a total of about "
        f"**{max_chars:,} characters**."
    )

st.write("---")

# -------------------------------------------------------------------
# 2. Add your content
# -------------------------------------------------------------------

st.subheader("1. Add your content")

uploaded_file = st.file_uploader(
    "Upload a report file (TXT, MD, PDF, DOCX, CSV).",
    type=["txt", "md", "pdf", "docx", "csv"],
)

pasted_text = st.text_area(
    "Or paste text manually",
    placeholder="Paste meeting notes, reports, or any free-text content...",
    height=200,
)

combined_text = ""


def read_uploaded_text(file) -> str:
    raw = file.read()
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return raw.decode("latin-1", errors="ignore")


if uploaded_file is not None:
    combined_text += read_uploaded_text(uploaded_file)

if pasted_text.strip():
    if combined_text:
        combined_text += "\n\n"
    combined_text += pasted_text.strip()

max_chars = plan_info.get("max_chars", 200_000)
if combined_text and len(combined_text) > max_chars:
    st.warning(
        f"Your content is longer than your plan allows ({len(combined_text):,} > {max_chars:,} characters). "
        "We’ll automatically trim it before sending it to the AI."
    )
    combined_text = combined_text[:max_chars]

st.write("---")

# -------------------------------------------------------------------
# 3. Generate summary
# -------------------------------------------------------------------

st.subheader("2. Generate a summary")

if st.button("Generate Business Summary"):
    if not email.strip():
        st.error("Please enter your email above first.")
    elif not combined_text.strip():
        st.error("Please upload a file or paste some text to summarize.")
    else:
        payload = {
            "email": email.strip(),
            "text": combined_text,
        }

        with st.expander("Debug: request payload being sent to /summarize", expanded=False):
            st.json(payload)

        try:
            resp = requests.post(
                f"{BACKEND_URL}/summarize",
                json=payload,
                timeout=120,
            )
            if resp.status_code == 422:
                st.error(
                    f"Backend returned 422 (Unprocessable Entity). "
                    f"Details: {resp.json()}"
                )
            else:
                resp.raise_for_status()
                data = resp.json()
                summary = data.get("summary", "")

                st.success("Summary generated!")
                st.subheader("Business-friendly summary")
                st.write(summary)

                with st.expander("Details about how your plan was applied"):
                    st.json(data)
        except Exception as e:
            st.error(f"Summarization failed: Network or backend error: {e}")
