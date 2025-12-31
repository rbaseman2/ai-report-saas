import os
import streamlit as st
import requests

st.set_page_config(page_title="Upload Data", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set in the Streamlit service.")
    st.stop()

st.title("Upload Data")

# Keep the rest of your page intact as much as possible.
# This update only changes the backend calls so you DON'T send multipart to /generate-summary (which expects JSON).

uploaded_file = st.file_uploader("Upload a document (PDF)", type=["pdf"])
email = st.text_input("Account Email (used to check subscription)", value=st.session_state.get("email", ""))

col1, col2 = st.columns([1, 1])

with col1:
    if st.button("Upload", type="primary", disabled=not uploaded_file):
        try:
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
            data = {"email": email} if email else {}
            resp = requests.post(f"{BACKEND_URL}/upload", files=files, data=data, timeout=120)
            if resp.status_code != 200:
                st.error(f"Upload failed ({resp.status_code}): {resp.text}")
            else:
                payload = resp.json()
                st.session_state["upload_id"] = payload.get("upload_id")
                st.success(f"Uploaded OK. upload_id={st.session_state['upload_id']}")
        except Exception as e:
            st.exception(e)

with col2:
    st.info("After uploading, go to Billing to generate your summary. Billing will use upload_id from session state.")

# Debug / visibility
if st.session_state.get("upload_id"):
    st.caption(f"Current upload_id: {st.session_state['upload_id']}")
