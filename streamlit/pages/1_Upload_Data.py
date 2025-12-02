import streamlit as st
import requests
import os

# -------------------------------
# CONFIG
# -------------------------------
st.set_page_config(page_title="Upload Data – AI Report", page_icon="📄")

BACKEND_URL = os.getenv("BACKEND_URL")

if not BACKEND_URL:
    st.error("Backend URL missing. Set BACKEND_URL in Render environment variables.")
    st.stop()

# -------------------------------
# PAGE TITLE
# -------------------------------
st.title("Upload Data & Generate a Business-Friendly Summary")

st.write("""
Turn dense reports, notes, and long documents into a clear business summary.
Use the same email you subscribed with.
""")

# -------------------------------
# EMAIL FIELD (required)
# -------------------------------
email = st.text_input(
    "Your email",
    value=st.session_state.get("billing_email", ""),
    placeholder="you@example.com",
    help="Use the same email you subscribed with on the Billing page."
)

# Keep in session
st.session_state["billing_email"] = email


# -------------------------------
# FILE UPLOAD OR TEXT AREA
# -------------------------------
st.subheader("1. Add your content")

uploaded_file = st.file_uploader(
    "Upload a report file (TXT, MD, PDF, DOCX, CSV). Max 200MB per file.",
    type=["txt", "md", "pdf", "docx", "csv"]
)

pasted_text = st.text_area(
    "Or paste text manually",
    height=250,
    placeholder="Paste meeting notes, reports, or any free-text content…"
)

combined_text = ""

filename = None

if uploaded_file:
    filename = uploaded_file.name
    combined_text = uploaded_file.read().decode(errors="ignore")

elif pasted_text.strip():
    filename = "pasted_text.txt"
    combined_text = pasted_text


# -------------------------------
# GENERATE SUMMARY
# -------------------------------
st.subheader("2. Generate a summary")

if st.button("Generate Business Summary"):

    # Validate inputs
    if not email:
        st.error("Please enter your email before generating a summary.")
        st.stop()

    if not combined_text.strip():
        st.error("Please upload a file or paste text before generating a summary.")
        st.stop()

    # Build the payload EXACTLY how the backend expects it
    payload = {
        "email": email,                        # ← REQUIRED
        "content": combined_text,              # ← REQUIRED
        "filename": filename,
        "char_count": len(combined_text)
    }

    # Debug panel
    with st.expander("Debug: request payload being sent to /summarize"):
        st.json(payload)

    # Send request to backend
    try:
        response = requests.post(
            f"{BACKEND_URL}/summarize",
            json=payload,
            timeout=120
        )
    except Exception as e:
        st.error(f"Network or backend error: {e}")
        st.stop()

    # Show backend errors clearly
    if response.status_code != 200:
        st.error(f"Backend returned {response.status_code}: {response.text}")
        st.stop()

    # SUCCESS
    result = response.json()
    st.success("Summary generated successfully!")

    st.subheader("Your Summary")
    st.write(result.get("summary", "(No summary returned)"))
