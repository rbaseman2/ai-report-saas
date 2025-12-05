# server/webhook.py

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import stripe
from openai import OpenAI
import requests  # <── NEW

# -------------------------------------------------------------------
# Environment / config
# -------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_BASIC_ID = os.getenv("PRICE_BASIC")
PRICE_PRO_ID = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE_ID = os.getenv("PRICE_ENTERPRISE")

SUCCESS_URL = os.getenv("SUCCESS_URL")
CANCEL_URL = os.getenv("CANCEL_URL")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# NEW – email config
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY
openai_client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Models & limits
# -------------------------------------------------------------------

class PlanLimits(BaseModel):
    plan: str
    max_documents: int
    max_chars: int

DEFAULT_LIMITS = PlanLimits(plan="free", max_documents=5, max_chars=200_000)
BASIC_LIMITS = PlanLimits(plan="basic", max_documents=20, max_chars=400_000)
PRO_LIMITS = PlanLimits(plan="pro", max_documents=75, max_chars=1_500_000)
ENTERPRISE_LIMITS = PlanLimits(plan="enterprise", max_documents=250, max_chars=5_000_000)


def _map_price_to_limits(price_id: str) -> PlanLimits:
    if price_id == PRICE_BASIC_ID:
        return BASIC_LIMITS
    if price_id == PRICE_PRO_ID:
        return PRO_LIMITS
    if price_id == PRICE_ENTERPRISE_ID:
        return ENTERPRISE_LIMITS
    return DEFAULT_LIMITS


def get_limits_for_email(email: str) -> PlanLimits:
    if not email:
        return DEFAULT_LIMITS
    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return DEFAULT_LIMITS

        customer = customers.data[0]
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="active",
            limit=1,
            expand=["data.items.data.price"],
        )
        if not subs.data:
            return DEFAULT_LIMITS

        sub = subs.data[0]
        item = sub["items"]["data"][0]
        price_id = item["price"]["id"]
        return _map_price_to_limits(price_id)
    except Exception:
        return DEFAULT_LIMITS


class CheckoutRequest(BaseModel):
    plan: str
    email: str


class SummarizeRequest(BaseModel):
    email: str           # subscriber’s/billing email
    text: str           # content to summarize
    send_to_email: Optional[str] = None  # <── NEW (client email)


class SummarizeResponse(BaseModel):
    summary: str
    plan: str
    max_chars: int
    used_chars: int


# -------------------------------------------------------------------
# Email helper
# -------------------------------------------------------------------

def send_summary_email(to_email: str, summary: str, plan: str, used_chars: int):
    """
    Send the summary via SendGrid. Fail silently (log only) so the user
    still gets the summary even if email breaks.
    """
    if not SENDGRID_API_KEY or not FROM_EMAIL:
        # If email isn't configured, just skip
        return

    subject = "Your AI-generated report summary"
    text_body = (
        "Hi,\n\n"
        "Here is your AI-generated summary.\n\n"
        f"Plan: {plan}\n"
        f"Characters summarized: {used_chars}\n\n"
        "Summary:\n\n"
        f"{summary}\n\n"
        "Best regards,\n"
        "RobAlSolutions AI Report"
    )

    html_body = f"""
    <p>Hi,</p>
    <p>Here is your AI-generated summary.</p>
    <p><b>Plan:</b> {plan}<br>
       <b>Characters summarized:</b> {used_chars}</p>
    <p><b>Summary:</b></p>
    <pre style="white-space:pre-wrap;font-family:system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
{summary}
    </pre>
    <p>Best regards,<br>RobAlSolutions AI Report</p>
    """

    payload = {
        "personalizations": [
            {"to": [{"email": to_email}], "subject": subject}
        ],
        "from": {"email": FROM_EMAIL, "name": "AI Report"},
        "content": [
            {"type": "text/plain", "value": text_body},
            {"type": "text/html", "value": html_body},
        ],
    }

    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers=headers,
            json=payload,
            timeout=10,
        )
    except Exception:
        # You could log this to stdout; Render will capture it
        pass


# -------------------------------------------------------------------
# Endpoints (health, subscription, checkout) unchanged… 
# (keep your existing ones here)
# -------------------------------------------------------------------

@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest):
    email = req.email.strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    limits = get_limits_for_email(email)
    max_chars = limits.max_chars

    HARD_CAP = 60_000
    effective_cap = min(max_chars, HARD_CAP)
    text = req.text[:effective_cap]
    used = len(text)

    if used == 0:
        raise HTTPException(status_code=400, detail="No text provided")

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI assistant that turns long, dense reports into a "
                        "concise, business-friendly summary for executives and stakeholders. "
                        "Highlight key points, risks, action items, and recommendations."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.4,
        )

        summary = completion.choices[0].message.content.strip()

        # NEW – email summary to client if requested
        if req.send_to_email:
            send_summary_email(
                to_email=req.send_to_email.strip(),
                summary=summary,
                plan=limits.plan,
                used_chars=used,
            )

        return SummarizeResponse(
            summary=summary,
            plan=limits.plan,
            max_chars=max_chars,
            used_chars=used,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
