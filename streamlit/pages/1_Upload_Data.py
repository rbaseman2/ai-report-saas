# 1_Upload_Data.py
import os
import io
import textwrap
from typing import Optional

import requests
import streamlit as st

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------
st.set_page_config(page_title="Upload Data – AI Report", page_icon="📤")

# Read backend URL only from environment so we don't hit Streamlit secrets
BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

if not BACKEND_URL:
    st.error(
        "BACKEND_URL is not configured. Set it in your Render environment "
        "for the frontend service."
    )
    st.stop()

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def read_file_to_text(upload) -> str:
    """Convert an uploaded file (txt, md, pdf, docx, csv) into plain text."""
    if upload is None:
        return ""

    name = upload.name.lower()

    # Simple text-like formats
    if any(name.endswith(ext) for ext in [".txt", ".md", ".csv", ".log"]):
        raw = upload.read()
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return raw.decode("latin-1", errors="ignore")

    # For now, just read binary-ish formats as best-effort text.
    # (You can later plug in real PDF/DOCX parsing here.)
    raw = upload.read()
    return raw.decode("utf-8", errors="ignore")


def fetch_subscription(email: str) -> dict:
    """
    Ask the backend what plan/limits this user has.
    Falls back to Free if anything goes wrong.
    """
    default = {
        "plan": "free",
        "max_documents": 5,
        "max_chars": 200_000,
    }

    if not email:
        return default

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=15,
        )
        if resp.status_code == 404:
            return default

        resp.raise_for_status()
        data = resp.json() or {}
        return {
            "plan": data.get("plan", "free"),
            "max_documents": data.get("max_documents", default["max_documents"]),
            "max_chars": data.get("max_chars", default["max_chars"]),
        }
    except Exception as e:
        st.warning(f"Could not verify subscription; using Free limits. ({e})")
        return default


def summarize(
    *,
    email: str,
    plan: str,
    content: str,
    client_email: Optional[str],
    send_to_client: bool,
) -> dict:
    """
    Call the backend /summarize endpoint.
    """
    payload = {
        "email": email,
        "plan": plan,
        "content": content,
    }

    # Only send these if a client email was provided
    if client_email:
        payload["client_email"] = client_email
        payload["send_to_client"] = bool(send_to_client)

    resp = requests.post(
        f"{BACKEND_URL}/summarize",
        json=payload,
        timeout=60,
    )

    # Raise for Streamlit to catch & show nicely
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------
# UI
# --------------------------------------------------------------------
st.title("Upload Data & Generate a Business-Friendly Summary")
st.write(
    "Turn dense reports into clear, client-ready summaries you can drop into emails, "
    "slide decks, or status updates."
)

# --- User / billing email (required for limits & logging) ---
user_email = st.text_input(
    "Your email (used for your subscription & limits)",
    value="",
    placeholder="you@example.com",
)

if user_email:
    sub_info = fetch_subscription(user_email)
else:
    sub_info = {
        "plan": "free",
        "max_documents": 5,
        "max_chars": 200_000,
    }

plan = sub_info["plan"]
max_chars = sub_info["max_chars"]

plan_label = {
    "free": "Free plan",
    "basic": "Basic plan",
    "pro": "Pro plan",
    "enterprise": "Enterprise plan",
}.get(plan, plan.capitalize())

with st.container():
    st.success(
        f"Status: **{plan_label}**. "
        f"You can upload up to **{sub_info['max_documents']} reports per month** "
        f"and a total of about **{sub_info['max_chars']:,} characters**."
    )

st.markdown("---")

# --- Client email options (new) ---
st.subheader("Client delivery (optional)")
client_email = st.text_input(
    "Client email (optional)",
    value="",
    placeholder="client@company.com",
    help="If provided, you can have the summary emailed directly to your client.",
)

send_to_client = st.checkbox(
    "Email this summary to the client address above",
    value=False,
    help="Your backend will send the summary to this client email after it is generated.",
    disabled=not client_email,
)

st.markdown("---")

# --- Upload + manual text ---
st.subheader("1. Add your content")

uploaded_file = st.file_uploader(
    "Upload a report file (TXT, MD, PDF, DOCX, CSV)",
    type=["txt", "md", "pdf", "docx", "csv"],
)

manual_text = st.text_area(
    "Or paste text manually",
    height=220,
    placeholder="Paste meeting notes, reports, or any free-text content…",
)

file_text = read_file_to_text(uploaded_file)
combined_text = "\n\n".join(part for part in [file_text, manual_text] if part).strip()

char_count = len(combined_text)

st.caption(f"Characters in this request: **{char_count:,}** of your ~{max_chars:,} monthly limit.")

if char_count == 0:
    st.info("Upload a file, paste some text, or both to get started.")

if char_count > max_chars:
    st.error(
        "This request is larger than your monthly character allowance for your plan. "
        "Try trimming the content or upgrading on the **Billing** page."
    )

st.markdown("---")

# --- Debug dropdown (helps us during development/support) ---
with st.expander("Debug: request payload that will be sent to the backend", expanded=False):
    st.json(
        {
            "email": user_email or "(missing)",
            "plan": plan,
            "content_preview": textwrap.shorten(combined_text or "", width=180),
            "client_email": client_email or None,
            "send_to_client": bool(send_to_client and client_email),
        }
    )

# --- Generate summary button ---
st.subheader("2. Generate a summary")

button_disabled = not (user_email and combined_text and char_count <= max_chars)

if st.button("Generate Business Summary", type="primary", disabled=button_disabled):
    if not user_email:
        st.error("Please enter your email so we can apply the right limits to your account.")
    elif not combined_text:
        st.error("Please upload a file or paste some text to summarize.")
    elif char_count > max_chars:
        st.error("This request exceeds your plan's character limit.")
    else:
        with st.spinner("Contacting the AI backend and generating your summary…"):
            try:
                result = summarize(
                    email=user_email,
                    plan=plan,
                    content=combined_text,
                    client_email=client_email or None,
                    send_to_client=send_to_client and bool(client_email),
                )
            except requests.HTTPError as e:
                try:
                    err_json = e.response.json()
                except Exception:
                    err_json = {"detail": str(e)}
                st.error(f"Backend error: {err_json}")
            except Exception as e:
                st.error(f"Network or backend error: {e}")
            else:
                summary = result.get("summary") or result.get("data") or ""
                if not summary:
                    st.warning("The backend responded, but no summary was found in the response.")
                else:
                    st.success("Summary generated!")
                    st.markdown("### Summary")
                    st.write(summary)

                # Optional flag from backend letting us know if it emailed the client
                if result.get("emailed_client") and client_email:
                    st.info(f"Summary was emailed to **{client_email}**.")
                elif send_to_client and client_email:
                    st.info(
                        "The request asked to email the client. "
                        "Check your backend logs to confirm the email was sent."
                    )
