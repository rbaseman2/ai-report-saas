import os
import requests
import streamlit as st

st.set_page_config(page_title="Upload Data – AI Report", layout="wide")

st.title("Upload Data")

BACKEND_URL = os.getenv("BACKEND_URL")
if not BACKEND_URL:
    st.error("BACKEND_URL is not configured.")
    st.stop()

if "billing_email" not in st.session_state:
    st.session_state.billing_email = ""

if "current_plan" not in st.session_state:
    st.session_state.current_plan = None

if "subscription_status" not in st.session_state:
    st.session_state.subscription_status = "none"

st.markdown("Billing email (used to look up your subscription)")
email = st.text_input("", value=st.session_state.billing_email, placeholder="you@example.com")

def check_plan():
    if not email:
        st.warning("Please enter a billing email first.")
        return

    try:
        r = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=20
        )
    except Exception as e:
        st.error(f"Error contacting backend: {e}")
        return

    if r.status_code != 200:
        st.error(f"Backend error: {r.status_code}")
        try:
            st.code(r.json())
        except Exception:
            st.write(r.text)
        return

    data = r.json() or {}
    st.session_state.billing_email = email
    st.session_state.current_plan = data.get("plan")  # may be None
    st.session_state.subscription_status = data.get("status") or "none"

st.button("Check subscription plan", on_click=check_plan)

# ---- SAFE DISPLAY (no NoneType.capitalize)
current_plan = st.session_state.current_plan
plan_value = current_plan or "none"
plan_label = plan_value.capitalize() if isinstance(plan_value, str) else "none"
status_label = st.session_state.subscription_status or "none"

st.markdown(f"**Current plan (for summaries):** `{plan_label}`")
st.markdown(f"**Status:** `{status_label}`")

st.divider()

st.write("Upload a report file (TXT, MD, PDF, DOCX, CSV).")
uploaded = st.file_uploader(
    "Drag and drop files here",
    type=["txt", "md", "pdf", "docx", "csv"],
    accept_multiple_files=False
)

st.write("Or paste text manually")
manual_text = st.text_area("", height=180)

st.divider()

st.header("2. Generate a summary")

email_summary = st.checkbox("Email this summary to someone", value=False)
recipient_email = ""
if email_summary:
    recipient_email = st.text_input("Recipient email", value="")

def generate_summary():
    if not st.session_state.billing_email:
        st.warning("Enter billing email and click 'Check subscription plan' first.")
        return

    if not uploaded and not manual_text.strip():
        st.warning("Upload a file or paste text first.")
        return

    payload = {
        "billing_email": st.session_state.billing_email,
        "send_email": bool(email_summary),
        "recipient_email": recipient_email.strip() if email_summary else "",
        "text": manual_text.strip(),
    }

    files = None
    if uploaded:
        files = {"file": (uploaded.name, uploaded.getvalue())}

    try:
        r = requests.post(f"{BACKEND_URL}/generate-summary", data=payload, files=files, timeout=120)
    except Exception as e:
        st.error(f"Error contacting backend: {e}")
        return

    if r.status_code != 200:
        st.error(f"Backend error: {r.status_code}")
        try:
            st.code(r.json())
        except Exception:
            st.write(r.text)
        return

    data = r.json() or {}
    summary = data.get("summary") or ""
    email_sent = bool(data.get("email_sent"))

    st.subheader("Summary:")
    st.write(summary if summary else "(No summary returned)")

    if email_summary:
        if email_sent:
            st.success(f"Email sent to {recipient_email.strip()}")
        else:
            st.warning("Email was requested but was not sent. Check backend logs / Brevo config.")

st.button("Generate Business Summary", on_click=generate_summary)
