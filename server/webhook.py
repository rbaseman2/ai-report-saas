import os
import json
import logging
from typing import Optional, Dict, Any, Tuple

import stripe
import requests

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from email_validator import validate_email, EmailNotValidError
from openai import OpenAI

# --------------------------------------------------
# App + logging
# --------------------------------------------------
logger = logging.getLogger("ai-report-backend")
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# --------------------------------------------------
# CORS
# --------------------------------------------------
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins.split(",")] if allowed_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# Stripe config (UNCHANGED)
# --------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "")

stripe.api_key = STRIPE_SECRET_KEY

PLAN_TO_PRICE = {
    "basic": os.getenv("STRIPE_PRICE_BASIC", ""),
    "pro": os.getenv("STRIPE_PRICE_PRO", ""),
    "enterprise": os.getenv("STRIPE_PRICE_ENTERPRISE", ""),
}
PRICE_TO_PLAN = {v: k for k, v in PLAN_TO_PRICE.items() if v}

# --------------------------------------------------
# OpenAI (UNCHANGED)
# --------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# --------------------------------------------------
# Email (Brevo) — NEW HELPER ONLY
# --------------------------------------------------
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "admin@robaisolutions.com")

def _send_email_via_brevo(to_email: str, subject: str, body_text: str) -> bool:
    """
    Sends transactional email via Brevo.
    Safe, isolated helper. Does not affect any other logic.
    """
    if not BREVO_API_KEY:
        logger.error("BREVO_API_KEY not set")
        return False

    payload = {
        "sender": {"email": EMAIL_FROM},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body_text,
    }

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers=headers,
        data=json.dumps(payload),
        timeout=10,
    )

    if resp.status_code >= 400:
        logger.error(f"Brevo email failed: {resp.status_code} {resp.text}")
        return False

    return True

# --------------------------------------------------
# Tier enforcement (UNCHANGED)
# --------------------------------------------------
CHAR_LIMITS = {
    "basic": 8000,
    "pro": 15000,
    "enterprise": 25000,
}
ACTIVE_SUB_STATUSES = {"active", "trialing"}

# --------------------------------------------------
# Models (UNCHANGED)
# --------------------------------------------------
class CheckoutRequest(BaseModel):
    plan: str
    email: EmailStr

class CheckoutResponse(BaseModel):
    url: str

class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    status: str
    plan: str
    active: bool

class GenerateSummaryResponse(BaseModel):
    summary: str
    plan: str
    email_sent: bool

# --------------------------------------------------
# Helpers (UNCHANGED)
# --------------------------------------------------
def _safe_email(email: str) -> str:
    try:
        validate_email(email)
        return email
    except EmailNotValidError:
        raise HTTPException(status_code=400, detail="Invalid email address")

def _truncate_for_plan(text: str, plan: str) -> str:
    limit = CHAR_LIMITS.get(plan, CHAR_LIMITS["basic"])
    return text[:limit]

def _openai_summarize(text: str, plan: str) -> str:
    if not openai_client:
        raise HTTPException(status_code=500, detail="OpenAI not configured")

    model = "gpt-4o-mini"
    resp = openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Summarize clearly and professionally."},
            {"role": "user", "content": text},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

# --------------------------------------------------
# Health
# --------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}

# --------------------------------------------------
# Generate summary (EMAIL SEND ADDED, LOGIC UNCHANGED)
# --------------------------------------------------
@app.post("/generate-summary", response_model=GenerateSummaryResponse)
async def generate_summary(request: Request):
    body = await request.json()

    billing_email = _safe_email(body.get("billing_email", ""))
    recipient_email = _safe_email(body.get("recipient_email", ""))
    extracted_text = body.get("extracted_text", "")
    filename = body.get("filename", "document")

    plan = "basic"
    extracted_text = _truncate_for_plan(extracted_text, plan)

    summary = _openai_summarize(extracted_text, plan)

    subject = f"AI Report Summary: {filename}"
    email_sent = _send_email_via_brevo(
        recipient_email,
        subject,
        summary,
    )

    return GenerateSummaryResponse(
        summary=summary,
        plan=plan,
        email_sent=email_sent,
    )
