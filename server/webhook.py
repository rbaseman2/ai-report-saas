# server/webhook.py

"""
Backend for AI Report SaaS

Exposes:
- GET  /health                      : simple health check
- POST /summarize                   : generate a business-friendly summary
- POST /create-checkout-session     : create a Stripe Checkout session
- POST /stripe-webhook              : handle Stripe webhooks

This version:
- Does NOT use psycopg2 or any DB driver.
- Accepts {"plan": "...", "email": "..."} from the frontend when creating a
  Checkout session.
- Attaches the email to the Checkout session via customer_email.
- Is written to be friendly with your existing Streamlit frontend.
"""

import os
import logging
from typing import Optional, Literal, Dict, Any

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

import stripe
from openai import OpenAI


# ---------------------------------------------------------------------------
# Basic setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-report-backend")

app = FastAPI(title="AI Report Backend")

# Stripe keys & config
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

PRICE_BASIC = os.environ.get("PRICE_BASIC")          # price_...
PRICE_PRO = os.environ.get("PRICE_PRO")              # price_...
PRICE_ENTERPRISE = os.environ.get("PRICE_ENTERPRISE")

SUCCESS_URL = os.environ.get("SUCCESS_URL")  # e.g. https://ai-report-saas.onrender.com/Billing?status=success
CANCEL_URL = os.environ.get("CANCEL_URL")    # e.g. https://ai-report-saas.onrender.com/Billing?status=cancel

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logger.warning("STRIPE_SECRET_KEY is not set; Stripe routes will fail.")

# OpenAI client
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set; /summarize will fail without it.")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Map plan names used by the frontend to Stripe price IDs
PLAN_TO_PRICE: Dict[str, Optional[str]] = {
    "basic": PRICE_BASIC,
    "pro": PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SummarizeRequest(BaseModel):
    text: str
    email: Optional[EmailStr] = None
    plan: Optional[str] = None  # "free", "basic", "pro", "enterprise", etc.

    class Config:
        extra = "ignore"  # ignore any unexpected fields from the frontend


class SummarizeResponse(BaseModel):
    summary: str


class CheckoutRequest(BaseModel):
    plan: Literal["basic", "pro", "enterprise"]
    email: EmailStr

    class Config:
        extra = "ignore"


class CheckoutResponse(BaseModel):
    checkout_url: str


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, str]:
    """
    Simple health endpoint used by Render to check liveness.
    """
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Summarization endpoint
# ---------------------------------------------------------------------------

BUSINESS_SUMMARY_SYSTEM_PROMPT = """
You are an assistant that turns long business or technical documents into
clear, client-ready executive summaries.

Write in concise, neutral business language suitable for non-technical
stakeholders. Focus on:
- key insights and findings
- risks or issues
- decisions made or required
- clear, concrete recommended next actions

Structure the answer with short sections and bullet points where helpful.
Avoid medical or patient language — this tool is for general business use.
"""


@app.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest):
    """
    Generate a business-friendly summary for the given text.
    """
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured.")

    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is empty.")

    # Optional: light guardrails on length based on plan
    # (You can tune these numbers as you like.)
    plan = (req.plan or "free").lower()
    max_chars_by_plan = {
        "free": 8000,
        "basic": 20000,
        "pro": 60000,
        "enterprise": 120000,
    }
    max_chars = max_chars_by_plan.get(plan, max_chars_by_plan["free"])
    if len(text) > max_chars:
        text = text[:max_chars]

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": BUSINESS_SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Summarize the following content for business stakeholders. "
                        "Include key insights, risks, and recommended actions.\n\n"
                        f"{text}"
                    ),
                },
            ],
            temperature=0.4,
            max_tokens=900,
        )
        summary_text = completion.choices[0].message.content.strip()
        return SummarizeResponse(summary=summary_text)

    except Exception as e:
        logger.exception("Error during summarization")
        raise HTTPException(status_code=500, detail=f"Summarization failed: {e}")


# ---------------------------------------------------------------------------
# Stripe Checkout session endpoint
# ---------------------------------------------------------------------------

@app.post("/create-checkout-session", response_model=CheckoutResponse)
def create_checkout_session(req: CheckoutRequest):
    """
    Create a Stripe Checkout session for a subscription plan.

    The frontend should POST:
        {
            "plan": "basic" | "pro" | "enterprise",
            "email": "user@example.com"
        }

    We resolve the plan to a Stripe Price ID, attach the email as customer_email,
    and return the Checkout URL.
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe API key not configured.")

    price_id = PLAN_TO_PRICE.get(req.plan)
    if not price_id:
        logger.error("No Stripe price configured for plan '%s'", req.plan)
        raise HTTPException(
            status_code=422,
            detail=f"No Stripe price configured for plan '{req.plan}'."
        )

    if not SUCCESS_URL or not CANCEL_URL:
        raise HTTPException(
            status_code=500,
            detail="SUCCESS_URL or CANCEL_URL is not configured in the backend."
        )

    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
            customer_email=str(req.email),
            allow_promotion_codes=True,
            metadata={
                "plan": req.plan,
                "app": "ai-report-saas",
            },
        )

        logger.info(
            "Created checkout session for %s plan, email=%s, id=%s",
            req.plan,
            req.email,
            checkout_session.id,
        )

        return CheckoutResponse(checkout_url=checkout_session.url)

    except stripe.error.StripeError as e:
        logger.exception("Stripe error while creating Checkout session")
        # surface a simplified error to the frontend but log the full details
        raise HTTPException(
            status_code=502,
            detail=f"Stripe error while creating Checkout session: {str(e)}",
        )
    except Exception as e:
        logger.exception("Unexpected error while creating Checkout session")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error while creating Checkout session: {e}",
        )


# ---------------------------------------------------------------------------
# Stripe webhook handler
# ---------------------------------------------------------------------------

@app.post("/stripe-webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
):
    """
    Handle Stripe webhook events.

    Currently this just logs events. In the future you can:
    - mark users as active subscribers
    - update internal limits, etc.
    """
    if not STRIPE_WEBHOOK_SECRET:
        logger.warning("Stripe webhook called, but STRIPE_WEBHOOK_SECRET is not set.")
        return JSONResponse(status_code=500, content={"error": "Webhook secret not configured"})

    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        # Invalid payload
        logger.exception("Invalid payload in Stripe webhook")
        return JSONResponse(status_code=400, content={"error": "Invalid payload"})
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        logger.exception("Invalid signature in Stripe webhook")
        return JSONResponse(status_code=400, content={"error": "Invalid signature"})

    event_type = event["type"]
    logger.info("Received Stripe event: %s", event_type)

    if event_type == "checkout.session.completed":
        session: Dict[str, Any] = event["data"]["object"]
        email = session.get("customer_details", {}).get("email") or session.get("customer_email")
        plan = session.get("metadata", {}).get("plan")

        logger.info(
            "Checkout completed: email=%s, plan=%s, session_id=%s",
            email,
            plan,
            session.get("id"),
        )
        # Here you could update a real database if you decide to add one.

    # You can add more event handlers (invoice.paid, customer.subscription.deleted, etc.)

    return JSONResponse(status_code=200, content={"status": "ok"})


# ---------------------------------------------------------------------------
# Root (optional)
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"message": "AI Report backend is running"}
