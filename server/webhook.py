import os
import logging
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import stripe
from openai import OpenAI

# ---------------------------------------------------------------------
# Configuration & clients
# ---------------------------------------------------------------------

logger = logging.getLogger("ai-report-backend")
logging.basicConfig(level=logging.INFO)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
PRICE_BASIC = os.getenv("PRICE_BASIC", "")
PRICE_PRO = os.getenv("PRICE_PRO", "")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8501")
SUCCESS_URL = os.getenv("SUCCESS_URL", f"{FRONTEND_URL}/Billing")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY is not set. Checkout will fail until configured.")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set. Summaries will fail until configured.")

stripe.api_key = STRIPE_SECRET_KEY
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------------------------------------------------
# FastAPI app setup
# ---------------------------------------------------------------------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, FRONTEND_URL.rstrip("/")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------

class SummaryRequest(BaseModel):
    text: str
    email: Optional[str] = None
    tier: Optional[Literal["free", "basic", "pro", "enterprise"]] = "free"


class SummaryResponse(BaseModel):
    summary: str


class CheckoutRequest(BaseModel):
    plan: Literal["basic", "pro", "enterprise"]
    email: str
    coupon: Optional[str] = None  # optional coupon code from the UI


class CheckoutResponse(BaseModel):
    url: str


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _plan_to_price_id(plan: str) -> str:
    plan = plan.lower()
    if plan == "basic":
        return PRICE_BASIC
    if plan == "pro":
        return PRICE_PRO
    if plan == "enterprise":
        return PRICE_ENTERPRISE
    raise ValueError(f"Unknown plan: {plan}")


def _truncate_text_for_model(text: str, max_chars: int = 20000) -> str:
    """
    Very simple safety guard so we don't try to send a 1.8M-character payload
    to the model. You can make this smarter later (chunking, etc.).
    """
    if len(text) > max_chars:
        logger.info("Input text length %s > %s, truncating", len(text), max_chars)
        return text[:max_chars]
    return text


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/summarize", response_model=SummaryResponse)
async def summarize(payload: SummaryRequest):
    """
    Summarize long reports/notes into a business-friendly summary.
    """
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the server.",
        )

    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="No text provided for summarization.")

    # Light guard against huge texts
    text = _truncate_text_for_model(payload.text)

    # You can vary behavior by tier if you want (e.g., longer summary for pro/enterprise)
    tier = (payload.tier or "free").lower()

    # Build a business-oriented prompt
    system_prompt = (
        "You are a professional business analyst. "
        "Given a long document or set of notes, you create a clear, concise summary "
        "that a non-technical client or business stakeholder can quickly understand. "
        "Highlight key points, decisions, risks, and any next steps. Avoid medical language."
    )

    user_prompt = (
        "Summarize the following content for a business client or audience. "
        "Focus on key insights, decisions, metrics, risks, and recommended next actions.\n\n"
        f"--- DOCUMENT START ---\n{text}\n--- DOCUMENT END ---"
    )

    try:
        logger.info("Calling OpenAI for tier=%s", tier)
        completion = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=900,
            temperature=0.3,
        )
        summary_text = completion.choices[0].message.content.strip()
        return SummaryResponse(summary=summary_text)
    except Exception as e:
        logger.exception("Error while generating summary: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {e}")


@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(payload: CheckoutRequest):
    """
    Create a Stripe Checkout Session for subscription.
    The Streamlit Billing page should POST here with {plan, email, coupon?}.
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured on the server.",
        )

    try:
        price_id = _plan_to_price_id(payload.plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Final success/cancel URLs. Stripe will substitute the session id.
    success_url = f"{SUCCESS_URL}?status=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{SUCCESS_URL}?status=cancelled"

    checkout_kwargs = {
        "success_url": success_url,
        "cancel_url": cancel_url,
        "mode": "subscription",
        "payment_method_types": ["card"],
        "line_items": [{"price": price_id, "quantity": 1}],
        "customer_email": payload.email,
        "allow_promotion_codes": True,  # also allow built-in coupons
    }

    # Optional explicit coupon code (requires corresponding Stripe coupon)
    if payload.coupon:
        checkout_kwargs["discounts"] = [{"coupon": payload.coupon}]

    try:
        session = stripe.checkout.Session.create(**checkout_kwargs)
        logger.info("Created Stripe session %s for %s (%s)", session.id, payload.email, payload.plan)
        return CheckoutResponse(url=session.url)
    except Exception as e:
        logger.exception("Error creating checkout session: %s", e)
        raise HTTPException(status_code=500, detail=f"Stripe checkout error: {e}")


# Optional: Stripe webhook endpoint (for future subscription tracking)
@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="Stripe-Signature")):
    if not STRIPE_WEBHOOK_SECRET:
        # If you haven't configured this yet, just acknowledge so Stripe stops retrying
        logger.warning("Received Stripe webhook but STRIPE_WEBHOOK_SECRET is not set.")
        return {"received": True}

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except Exception as e:
        logger.warning("Failed to verify Stripe webhook: %s", e)
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")

    # You can extend this to persist subscription info, etc.
    logger.info("Received Stripe event: %s", event["type"])
    return {"received": True}
