import json
import logging
import os

import stripe
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

# ---------- Logging ----------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Environment ----------

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_BASIC = os.environ.get("PRICE_BASIC")
PRICE_PRO = os.environ.get("PRICE_PRO")
PRICE_ENTERPRISE = os.environ.get("PRICE_ENTERPRISE")

SUCCESS_URL = os.environ.get("SUCCESS_URL")  # e.g. https://your-app.onrender.com/Billing
CANCEL_URL = os.environ.get("CANCEL_URL", SUCCESS_URL or "")

if not all([PRICE_BASIC, PRICE_PRO, PRICE_ENTERPRISE]):
    logger.warning("One or more Stripe price IDs (PRICE_BASIC/PRO/ENTERPRISE) are not set.")

PLAN_TO_PRICE = {
    "basic": PRICE_BASIC,
    "pro": PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

client = OpenAI()

# ---------- FastAPI app ----------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can tighten this to your frontend URL if you like
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Pydantic models ----------


class SummarizeRequest(BaseModel):
    text: str
    email: str | None = None


class SummarizeResponse(BaseModel):
    summary: str


class CheckoutRequest(BaseModel):
    email: str
    plan: str  # "basic", "pro", "enterprise"


class CheckoutResponse(BaseModel):
    checkout_url: str


# ---------- Routes ----------


@app.get("/health")
async def health():
    return {"status": "ok"}


BUSINESS_SYSTEM_PROMPT = (
    "You are an AI assistant that summarizes business documents for non-technical readers. "
    "Your audience might be clients, managers, or stakeholders who need a clear, concise view "
    "of the key points. Focus on:\n"
    "- Main objectives and context\n"
    "- Key insights, decisions, or results\n"
    "- Risks, issues, or concerns (if any)\n"
    "- Recommended next steps or actions\n\n"
    "Write in clear, professional language. Avoid jargon where possible, and keep the tone "
    "neutral and business-friendly."
)


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(body: SummarizeRequest):
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is empty")

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": BUSINESS_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.3,
            max_tokens=800,
        )

        summary = completion.choices[0].message.content.strip()
        return SummarizeResponse(summary=summary)
    except Exception as exc:
        logger.exception("Error during OpenAI summarization")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(body: CheckoutRequest):
    plan = body.plan.lower()
    price_id = PLAN_TO_PRICE.get(plan)

    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    if not SUCCESS_URL:
        raise HTTPException(
            status_code=500,
            detail="SUCCESS_URL is not configured in the backend environment.",
        )

    try:
        # Stripe Checkout for subscriptions
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=body.email,
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            # These URLs control where Stripe sends the user after checkout
            success_url=f"{SUCCESS_URL}?status=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{CANCEL_URL}?status=cancelled" if CANCEL_URL else SUCCESS_URL,
            allow_promotion_codes=True,  # enables coupon / promo code field
            billing_address_collection="auto",
        )

        logger.info("Created checkout session %s for %s (%s)", session.id, body.email, plan)
        return CheckoutResponse(checkout_url=session.url)
    except Exception as exc:
        logger.exception("Error creating Stripe Checkout session")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
):
    """
    Basic Stripe webhook handler.
    Right now this just verifies the signature (if configured) and logs the event.
    You can extend this later to store subscription status in a database.
    """
    payload = await request.body()

    try:
        if STRIPE_WEBHOOK_SECRET and stripe_signature:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=stripe_signature,
                secret=STRIPE_WEBHOOK_SECRET,
            )
        else:
            # No verification – for local testing only
            event = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        logger.exception("Failed to parse Stripe webhook")
        raise HTTPException(status_code=400, detail=f"Webhook error: {exc}")

    event_type = event.get("type")
    logger.info("Received Stripe event: %s", event_type)

    # Example places to extend logic:
    # - checkout.session.completed
    # - customer.subscription.updated
    # - customer.subscription.deleted

    return {"received": True}
