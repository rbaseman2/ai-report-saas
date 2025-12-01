import os
import io
import requests
import streamlit as st

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------

BACKEND_URL = os.getenv(
    "BACKEND_URL", "https://ai-report-backend-ubrx.onrender.com"
)

st.set_page_config(
    page_title="Upload Data – AI Report",
    page_icon="📄",
)

st.title("Upload Data & Generate a Business-Friendly Summary")

# --------------------------------------------------------------------
# 1. Email + plan detection
# --------------------------------------------------------------------

st.write(
    "Use the same email address you subscribed with on the **Billing** page."
)

email = st.text_input("Your email", value=st.session_state.get("billing_email", ""))

plan = "free"
limits = {"max_documents": 5, "max_chars": 200_000}
status_text = "Free plan. Summaries are shorter and input size is limited."

if email.strip():
    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email.strip()},
            timeout=25,
        )
        if resp.status_code == 404:
            # no active subscription: keep Free
            plan = "free"
            limits = {"max_documents": 5, "max_chars": 200_000}
            status_text = (
                "Free plan. We couldn't find an active subscription for this email."
            )
        else:
            resp.raise_for_status()
            data = resp.json()
            plan = data.get("plan", "free")
            limits = {
                "max_documents": data.get("max_documents", 5),
                "max_chars": data.get("max_chars", 200_000),
            }

            if plan == "pro":
                status_text = (
                    "Pro plan. Up to 30 documents per month with deeper summaries."
                )
            elif plan == "enterprise":
                status_text = (
                    "Enterprise plan. Highest limits and priority support."
                )
            else:
                status_text = "Free plan."
    except Exception as e:
        plan = "free"
        limits = {"max_documents": 5, "max_chars": 200_000}
        status_text = (
            "We couldn't verify your subscription just now, "
            "so we're treating you as on the Free plan for this session.\n\n"
            f"Technical details: {e}"
        )

st.session_state["plan"] = plan
st.info(f"Status: **{plan.capitalize()} plan**. {status_text}")

st.markdown("---")

# --------------------------------------------------------------------
# 2. Upload content
# --------------------------------------------------------------------

st.header("1. Add your content")

uploaded_file = st.file_uploader(
    "Upload a file",
    type=["txt", "md", "markdown", "pdf", "docx", "csv"],
)

manual_text = st.text_area(
    "Or paste text manually",
    height=200,
    placeholder="Paste meeting notes, reports, or any free-text content…",
)

st.markdown("---")

# --------------------------------------------------------------------
# 3. Generate summary
# --------------------------------------------------------------------

st.header("2. Generate a summary")

if st.button("Generate Business Summary"):
    if not email.strip():
        st.error("Please enter your email so we can check your subscription.")
    elif not uploaded_file and not manual_text.strip():
        st.error("Please upload a file or paste some text to summarize.")
    else:
        with st.spinner("Contacting summarization service…"):
            files = {}
            data = {"email": email.strip(), "text": manual_text}

            if uploaded_file is not None:
                # Send as a real multipart file
                files["file"] = (
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    uploaded_file.type or "application/octet-stream",
                )

            try:
                resp = requests.post(
                    f"{BACKEND_URL}/summarize",
                    data=data,
                    files=files if files else None,
                    timeout=120,
                )
                resp.raise_for_status()
                out = resp.json()
                summary = out.get("summary")

                if not summary:
                    st.error(
                        "Backend did not return a 'summary' field. "
                        "Please check the logs."
                    )
                else:
                    st.subheader("Business-Friendly Summary")
                    st.write(summary)
            except Exception as e:
                st.error(f"Summarization failed: {e}")
