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

SUCCESS_URL = "https://ai-report-saas.onrender.com/Billing?success=true"
CANCEL_URL = "https://ai-report-saas.onrender.com/Billing?cancel=true"



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
    text: str                      # content to summarize
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
    Wrapper around OpenAI to generate a business-style summary.
    """
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set – returning fallback summary.")
        return "Summary service is temporarily unavailable. Please try again later."

    try:
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
        "to": [{"email": to_email}],
        "replyTo": {"email": original_email},
        "subject": "Your AI-generated summary",
        "textContent": body,
    }

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={
                "api-key": BREVO_API_KEY,
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            timeout=10,
        )

        if resp.status_code >= 400:
            logger.error(
                "Brevo email failed: status=%s body=%s",
                resp.status_code,
                resp.text,
            )
        else:
            logger.info("Brevo email sent successfully: %s", resp.text)

    except Exception as e:
        logger.exception("Failed to send summary email via Brevo: %s", e)


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------


@app.post("/summarize")
async def summarize(req: SummarizeRequest):
    """
    Generate a summary and optionally email it.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text to summarize is required.")

    summary = generate_summary(req.text)

    if req.send_email and req.recipient_email:
        # Email failures are logged but won't break the API response
        try:
            send_summary_email(
                to_email=req.recipient_email,
                body=summary,
                original_email=req.email,
            )
        except Exception:
            logger.exception("Error while trying to send summary email.")

    return {"summary": summary}


def price_for_plan(plan: str) -> str:
    plan = plan.lower()
    if plan == "basic":
        return PRICE_BASIC
    if plan == "pro":
        return PRICE_PRO
    if plan == "enterprise":
        return PRICE_ENTERPRISE
    return None


@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutRequest):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe secret key not configured on the server.",
        )

    price_id = price_for_plan(data.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan selected.")

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            customer_email=str(data.email),
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
        )
        return {"sessionId": checkout_session["id"], "url": checkout_session["url"]}
    except Exception as e:
        logger.exception("Error creating Stripe Checkout Session: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Error creating checkout session. Please try again later.",
        )


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook handler.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET is not set on the server.")
        raise HTTPException(status_code=500, detail="Webhook secret is not configured.")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError as e:
        logger.error("Invalid payload: %s", e)
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error("Invalid signature: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    logger.info("Received Stripe event: %s", event["type"])

    return {"received": True}


@app.get("/health")
async def health():
    """
    Simple health check endpoint for Render.
    """
    return {"status": "ok"}
