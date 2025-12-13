import os
import json
import requests
import streamlit as st

st.set_page_config(page_title="Upload Data", page_icon="📄", layout="wide")

APP_VERSION = "2025-12-12 v10"

def get_backend_url() -> str:
    env_url = os.getenv("BACKEND_URL")
    if env_url and env_url.strip():
        return env_url.strip().rstrip("/")
    try:
        sec_url = st.secrets.get("BACKEND_URL")
        if sec_url:
            return str(sec_url).strip().rstrip("/")
    except Exception:
        pass
    return "http://localhost:8000"

BACKEND_URL = get_backend_url()

def safe_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return {"_raw": resp.text}

def get_subscription_status(email: str):
    r = requests.get(f"{BACKEND_URL}/subscription-status", params={"email": email}, timeout=30)
    data = safe_json(r)
    if r.status_code >= 400:
        raise RuntimeError(f"Backend error {r.status_code}: {data}")
    return data

def call_summary_api(
    billing_email: str,
    file_obj,
    pasted_text: str,
    send_email: bool,
    recipient_email: str
):
    """
    Expected backend endpoint: POST /summarize
    Supports either multipart file upload OR json text.
    """
    url = f"{BACKEND_URL}/summarize"

    # If file is provided, send multipart
    if file_obj is not None:
        files = {"file": (file_obj.name, file_obj.getvalue())}
        data = {
            "billing_email": billing_email,
            "send_email": str(send_email).lower(),
            "recipient_email": recipient_email or "",
        }
        r = requests.post(url, files=files, data=data, timeout=120)

    # Otherwise send pasted text as JSON
    else:
        payload = {
            "billing_email": billing_email,
            "text": pasted_text or "",
            "send_email": send_email,
            "recipient_email": recipient_email or "",
        }
        r = requests.post(url, json=payload, timeout=120)

    return r

# ---------------- UI ----------------
st.title("Upload Data")
st.caption(f"Upload build: {APP_VERSION}")

with st.expander("Debug (backend target)"):
    st.write("BACKEND_URL =", BACKEND_URL)

# Billing email (required to gate plan + usage)
billing_email = st.text_input(
    "Billing email (used to look up your subscription)",
    value=st.session_state.get("billing_email", ""),
    placeholder="you@example.com"
).strip()

if billing_email:
    st.session_state["billing_email"] = billing_email

check = st.button("Check subscription plan")

plan_box = st.empty()
status_box = st.empty()

current_plan = None
status = None

if check:
    if not billing_email:
        status_box.error("Enter a billing email first.")
    else:
        try:
            sub = get_subscription_status(billing_email)
            status = sub.get("status") or "none"
            current_plan = sub.get("plan")  # might be None
            st.session_state["sub_status"] = status
            st.session_state["sub_plan"] = current_plan

            plan_display = current_plan if current_plan else "None"
            plan_box.info(f"Current plan (for summaries): {plan_display}")
            status_box.info(f"Status: {status}")
        except Exception as e:
            status_box.error(str(e))

# Show persisted values (so it doesn't “disappear” after rerun)
if "sub_plan" in st.session_state or "sub_status" in st.session_state:
    persisted_plan = st.session_state.get("sub_plan")
    persisted_status = st.session_state.get("sub_status")
    plan_box.info(f"Current plan (for summaries): {persisted_plan if persisted_plan else 'None'}")
    status_box.info(f"Status: {persisted_status if persisted_status else 'none'}")

st.markdown("---")

uploaded_file = st.file_uploader(
    "Upload a report file (TXT, MD, PDF, DOCX, CSV).",
    type=["txt", "md", "pdf", "docx", "csv"]
)

pasted_text = st.text_area("Or paste text manually", height=160)

st.markdown("## 2. Generate a summary")

send_email = st.checkbox("Email this summary to someone", value=True)
recipient_email = st.text_input("Recipient email", value="").strip() if send_email else ""

generate = st.button("Generate Business Summary", type="primary")

result_box = st.empty()
details_box = st.empty()

if generate:
    # Basic validation
    if not billing_email:
        result_box.error("Billing email is required (so we can confirm plan).")
        st.stop()

    if uploaded_file is None and not (pasted_text and pasted_text.strip()):
        result_box.error("Please upload a file OR paste text.")
        st.stop()

    if send_email and not recipient_email:
        result_box.error("Recipient email is required when 'Email this summary' is checked.")
        st.stop()

    # Call backend
    with st.spinner("Generating summary..."):
        try:
            resp = call_summary_api(
                billing_email=billing_email,
                file_obj=uploaded_file,
                pasted_text=pasted_text.strip() if pasted_text else "",
                send_email=send_email,
                recipient_email=recipient_email
            )

            data = safe_json(resp)

            # Always show something if it failed
            if resp.status_code >= 400:
                result_box.error(f"Backend error {resp.status_code}")
                details_box.write(data)
                st.stop()

            # Pull summary from multiple possible keys
            summary = (
                data.get("summary")
                or data.get("business_summary")
                or data.get("result")
                or data.get("text")
            )

            email_sent = data.get("email_sent")
            email_error = data.get("email_error")

            if not summary:
                result_box.warning("Backend returned success, but no 'summary' field was found.")
                details_box.write(data)  # show raw payload so we can fix key mismatch
                st.stop()

            st.session_state["last_summary"] = summary

            result_box.success("Summary generated.")
            st.markdown("### Summary")
            st.write(summary)

            if send_email:
                if email_sent is True:
                    st.success(f"Email sent to {recipient_email}.")
                elif email_sent is False:
                    st.error(f"Email was NOT sent. Error: {email_error or 'Unknown email error'}")
                else:
                    st.warning("Backend did not confirm email_sent=True/False. Showing response:")
                    details_box.write(data)

        except Exception as e:
            result_box.error(f"Request failed: {e}")

# Show last summary after rerun
if st.session_state.get("last_summary"):
    st.markdown("### Last generated summary")
    st.write(st.session_state["last_summary"])
