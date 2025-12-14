import os
import streamlit as st
import requests

st.set_page_config(page_title="Upload Data", layout="wide")

BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
if not BACKEND_URL:
    st.error("BACKEND_URL environment variable is not set in the Streamlit service.")
    st.stop()

st.title("Upload Data")

# ----------------------------
# Sidebar navigation (MUST match actual filenames)
# ----------------------------
with st.sidebar:
    st.header("Navigation")

    # Home might be entrypoint, guard if missing
    try:
        st.page_link("Home.py", label="Home")
    except Exception:
        st.write("Home")

    # ✅ current page filename
    st.page_link("pages/1_Upload_Data.py", label="Upload Data", disabled=True)

    try:
        st.page_link("pages/2_Billing.py", label="Billing")
    except Exception:
        pass

    try:
        st.page_link("pages/3_Terms.py", label="Terms")
    except Exception:
        pass

    try:
        st.page_link("pages/4_Privacy.py", label="Privacy")
    except Exception:
        pass


# ----------------------------
# Helpers
# ----------------------------
def fetch_subscription(email: str):
    r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": email}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code}: {r.text}")
    return r.json()


# ----------------------------
# Billing email / subscription lookup
# ----------------------------
billing_email = st.text_input(
    "Billing email (used to look up your subscription)",
    value=st.session_state.get("billing_email", ""),
    placeholder="you@example.com",
)

if st.button("Check subscription plan"):
    st.session_state["billing_email"] = billing_email.strip()

plan = None
status = "none"
if st.session_state.get("billing_email", "").strip():
    try:
        sub = fetch_subscription(st.session_state["billing_email"])
        plan = sub.get("plan")  # may be None
        status = sub.get("status") or "none"
    except Exception as e:
        st.error(f"Error contacting backend: {e}")

st.markdown(f"**Current plan (for summaries):** {plan.title() if isinstance(plan, str) else 'None'}")
st.markdown(f"**Status:** {status}")

st.divider()

# ----------------------------
# Upload + Generate summary
# ----------------------------
st.write("Upload a report file (TXT, MD, PDF, DOCX, CSV).")
uploaded = st.file_uploader(" ", type=["txt", "md", "pdf", "docx", "csv"])

manual_text = st.text_area("Or paste text manually", height=180)

st.subheader("2. Generate a summary")
send_email = st.checkbox("Email this summary to someone", value=True)
recipient_email = st.text_input("Recipient email", value=st.session_state.get("recipient_email", ""))

if send_email:
    st.session_state["recipient_email"] = recipient_email.strip()

if st.button("Generate Business Summary"):
    if not st.session_state.get("billing_email", "").strip():
        st.error("Enter your billing email first and click 'Check subscription plan'.")
        st.stop()

    if not uploaded and not manual_text.strip():
        st.error("Upload a file or paste text first.")
        st.stop()

    if send_email and not recipient_email.strip():
        st.error("Enter a recipient email (or uncheck 'Email this summary to someone').")
        st.stop()

    try:
        # NOTE: this expects your backend to expose POST /generate-summary
        # Adjust the endpoint name here if yours is different.
        payload = {
            "billing_email": st.session_state["billing_email"],
            "recipient_email": recipient_email.strip() if send_email else None,
            "text": manual_text.strip() if manual_text.strip() else None,
        }

        files = None
        if uploaded:
            files = {"file": (uploaded.name, uploaded.getvalue())}

        with st.spinner("Generating summary..."):
            resp = requests.post(f"{BACKEND_URL}/generate-summary", data=payload, files=files, timeout=120)

        if resp.status_code != 200:
            st.error(f"Backend error {resp.status_code}")
            st.code(resp.text)
            st.stop()

        data = resp.json()
        summary = data.get("summary", "")
        email_sent = data.get("email_sent", False)

        st.success("Summary generated.")
        st.markdown("### Summary")
        st.write(summary)

        if send_email:
            if email_sent:
                st.success(f"Email sent to {recipient_email.strip()}")
            else:
                st.warning("Summary generated, but email was not sent (backend reported email_sent=false).")
        if data.get("email_error"):
            st.error(f"Email error: {data.get('email_error')}")

    except Exception as e:
        st.error(f"Unexpected error: {e}")