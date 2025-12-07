import os
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

import stripe
import requests

# -------------------------------------------------------------------
# Environment / configuration
# -------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

SUCCESS_URL = os.getenv("SUCCESS_URL", "https://example.com/success")
CANCEL_URL = os.getenv("CANCEL_URL", "https://example.com/cancel")

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Email / Brevo
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM", "rbaseman2@yahoo.com")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logger.warning("STRIPE_SECRET_KEY is not set – Stripe calls will fail.")

# -------------------------------------------------------------------
# FastAPI app + CORS
# -------------------------------------------------------------------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:8501", "http://127.0.0.1:8501", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------


class SummarizeRequest(BaseModel):
    email: EmailStr                # billing / user email
    text: str                      # content to summarize (already truncated in frontend)
    send_email: bool = False       # whether to email summary to someone
    recipient_email: Optional[EmailStr] = None  # optional recipient


class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: str  # "basic" | "pro" | "enterprise"


class WebhookEvent(BaseModel):
    id: str
    type: str
    data: dict


# -------------------------------------------------------------------
# Helpers: OpenAI summary
# -------------------------------------------------------------------


def generate_summary(text: str) -> str:
    """
    Very simple wrapper around OpenAI to generate a business-style summary.
    Adjust this to match the library you're using (openai / OpenAI client, etc).
    """
    if not OPENAI_API_KEY:
        # In case the key is missing, fail gracefully instead of 500.
        logger.error("OPENAI_API_KEY not set – returning fallback summary.")
        return "Summary service is temporarily unavailable. Please try again later."

    try:
        # Example using the official 'openai' client (you may need to adjust).
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)

        prompt = (
            "You are an assistant that writes concise, business-friendly summaries. "
            "Summarize the following content for busy professionals, focusing on key "
            "points, risks, opportunities, and recommended actions.\n\n"
            f"CONTENT:\n{text}"
        )

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You write clear business summaries."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
        )

        return completion.choices[0].message.content.strip()

    except Exception as e:
        logger.exception("Error while calling OpenAI: %s", e)
        return "There was an error generating the summary. Please try again later."


# -------------------------------------------------------------------
# Helpers: Email via Brevo
# -------------------------------------------------------------------


def send_summary_email(to_email: str, body: str, original_email: str):
    """
    Send the summary email via Brevo (Sendinblue) transactional API.
    Failures are logged but do not crash the request.
    """
    if not BREVO_API_KEY:
        logger.error("BREVO_API_KEY is not set – cannot send email.")
        return

    payload = {
        "sender": {"email": EMAIL_FROM},
        "to": [{"emai]()
