import os
import io
import textwrap
import requests
import streamlit as st

# ------------------------- Page config -------------------------
st.set_page_config(
    page_title="Upload Data – AI Report",
    page_icon="📄",
)

# ------------------------- Backend config ----------------------
BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")

if not BACKEND_URL:
    st.error(
        "BACKEND_URL is not set in the Streamlit environment. "
        "Set it to your FastAPI URL in Render → Environment."
    )
    st.stop()

# ------------------------- Helpers -----------------------------


@st.cache_data(show_spinner=False, ttl=60)
def fetch_subscription_status(email: str):
    """
    Ask the backend what plan this email is on.

    Returns:
        (plan: str, limits: dict)
        plan is 'free' | 'basic' | 'pro' | 'enterprise'
    """
    if not email:
        return "free", {"max_documents": 5, "max_chars": 200_000}

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=20,
        )

        # If the backend explicitly says "no subscription" -> treat as free
        if resp.status_code == 404:
            return "free", {"max_documents": 5, "max_chars": 200_000}

        resp.raise_for_status()
        data = resp.json()

        plan = data.get("plan", "free")
        limits = {
            "max_documents": data.get("max_documents", 5),
            "max_chars": data.get("max_chars", 200_000),
        }
        return plan, limits

    except Exception as e:
        # On any error, fail-soft to free, but show a warning
        st.warning(f"We couldn't verify your subscription (using Free plan for now). Details: {e}")
        return "free", {"max_documents": 5, "max_chars": 200_000}


def plan_label(plan: str) -> str:
    return {
        "free": "Free plan",
        "basic": "Basic plan",
        "pro": "Pro plan",
        "enterprise": "Enterprise plan",
    }.get(plan, "Free plan")


# ------------------------- UI -----------------------------


st.title("Upload Data & Generate a Business-Friendly Summary")

st.write(
    "Turn dense reports, meeting notes, and long documents into a clear, client-ready summary "
    "you can drop into emails, slide decks, or status updates."
)

# ----------- Email input (same email as Billing page) ----------
st.subheader("Your email")

email = st.text_input(
    "Use the same email address you subscribed with.",
    key="upload_email",
)

plan = "free"
limits = {"max_documents": 5, "max_chars": 200_000}

if email:
    plan, limits = fetch_subscription_status(email)

# Status banner
status_text = f"Status: **{plan_label(plan)}**."
if plan == "free":
    extra = (
        " Summaries are shorter and input size is limited. "
        "Upgrade on the **Billing** page for higher limits and deeper analysis."
    )
elif plan == "basic":
    extra = (
        f" You can upload up to {limits['max_documents']} documents per month with "
        f"about {limits['max_chars']:,} characters per summary."
    )
elif plan == "pro":
    extra = (
        f" You can upload up to {limits['max_documents']} documents per month with "
        f"about {limits['max_chars']:,} characters per summary."
    )
else:  # enterprise
    extra = " You have our highest limits. Contact us if you hit any ceilings."

st.info(status_text + extra)

st.markdown("---")

# -------------- 1. Add your content ---------------------
st.subheader("1. Add your content")

st.write("Upload a report or paste your content below. Supported formats: TXT, MD, PDF, DOCX, CSV.")

uploaded_file = st.file_uploader(
    "Upload a file",
    type=["txt", "md", "pdf", "docx", "csv"],
)

text_input = st.text_area(
    "Or paste text manually",
    height=250,
    placeholder="Paste meeting notes, reports, or any free-text content...",
)

# -------------- 2. Generate summary ---------------------
st.subheader("2. Generate a summary")

if st.button("Generate Business Summary", type="primary"):
    if not email:
        st.error("Please enter your email address above before generating a summary.")
        st.stop()

    if not uploaded_file and not text_input.strip():
        st.error("Please upload a file or paste some text to summarize.")
        st.stop()

    # Prepare content to send to backend
    files = None
    data = {"email": email}

    if uploaded_file is not None:
        # Send file to backend
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
    else:
        data["text"] = text_input

    with st.spinner("Generating summary..."):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/summarize",
                data=data,
                files=files,
                timeout=300,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.exceptions.RequestException as e:
            st.error(f"Summarization failed: Backend error: {e}")
            st.stop()

    summary = result.get("summary")
    tokens_used = result.get("tokens_used")

    if not summary:
        st.error("Backend did not return a summary.")
        st.stop()

    st.markdown("### Summary")
    st.write(summary)

    if tokens_used is not None:
        st.caption(f"Approximate tokens used: {tokens_used:,}")
