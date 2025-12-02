import os
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import stripe
from openai import OpenAI

# --------------------------------------------------
# Logging
# --------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------------------------------------------
# Environment & external clients
# --------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_BASIC_ID = os.getenv("PRICE_BASIC")       # e.g. price_xxx
PRICE_PRO_ID = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE_ID = os.getenv("PRICE_ENTERPRISE")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY not set – subscription checks will fail.")

stripe.api_key = STRIPE_SECRET_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

# Map price IDs → internal plan keys
PRICE_TO_PLAN = {}
if PRICE_BASIC_ID:
    PRICE_TO_PLAN[PRICE_BASIC_ID] = "basic"
if PRICE_PRO_ID:
    PRICE_TO_PLAN[PRICE_PRO_ID] = "pro"
if PRICE_ENTERPRISE_ID:
    PRICE_TO_PLAN[PRICE_ENTERPRISE_ID] = "enterprise"

PLAN_LIMITS = {
    "free": {
        "max_documents": 5,
        "max_chars": 200_000,
    },
    "basic": {
        "max_documents": 20,
        "max_chars": 400_000,
    },
    "pro": {
        "max_documents": 75,
        "max_chars": 1_500_000,
    },
    "enterprise": {
        "max_documents": 250,
        "max_chars": 5_000_000,
    },
}

# --------------------------------------------------
# FastAPI app & CORS
# --------------------------------------------------
app = FastAPI(title="AI Report Backend")

allowed_origins = [
    FRONTEND_URL,
    "http://localhost:8501",
    "http://127.0.0.1:8501",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# Pydantic models
# --------------------------------------------------
class CheckoutRequest(BaseModel):
    email: EmailStr
    tier: str  # "basic" | "pro" | "enterprise"


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    plan: str
    max_documents: int
    max_chars: int


class SummarizeRequest(BaseModel):
    email: EmailStr
    content: str
    filename: Optional[str] = None
    char_count: int


# --------------------------------------------------
# Utility functions
# --------------------------------------------------
def get_plan_for_email(email: str) -> SubscriptionStatusResponse:
    """
    Look up the customer's active Stripe subscription by email and map it to a plan.
    Returns a SubscriptionStatusResponse model.
    """
    if not STRIPE_SECRET_KEY:
        # Stripe not configured → treat everyone as free
        limits = PLAN_LIMITS["free"]
        return SubscriptionStatusResponse(
            email=email,
            plan="free",
            max_documents=limits["max_documents"],
            max_chars=limits["max_chars"],
        )

    try:
        customers = stripe.Customer.list(email=email, limit=1)
    except Exception as e:
        logger.exception("Error listing Stripe customers")
        limits = PLAN_LIMITS["free"]
        return SubscriptionStatusResponse(
            email=email,
            plan="free",
            max_documents=limits["max_documents"],
            max_chars=limits["max_chars"],
        )

    if not customers.data:
        limits = PLAN_LIMITS["free"]
        return SubscriptionStatusResponse(
            email=email,
            plan="free",
            max_documents=limits["max_documents"],
            max_chars=limits["max_chars"],
        )

    customer = customers.data[0]

    try:
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="active",
            limit=1,
        )
    except Exception:
        logger.exception("Error listing Stripe subscriptions")
        limits = PLAN_LIMITS["free"]
        return SubscriptionStatusResponse(
            email=email,
            plan="free",
            max_documents=limits["max_documents"],
            max_chars=limits["max_chars"],
        )

    if not subs.data:
        limits = PLAN_LIMITS["free"]
        return SubscriptionStatusResponse(
            email=email,
            plan="free",
            max_documents=limits["max_documents"],
            max_chars=limits["max_chars"],
        )

    subscription = subs.data[0]
    item = subscription["items"]["data"][0]
    price_id = item["price"]["id"]

    plan_key = PRICE_TO_PLAN.get(price_id, "basic")  # default to basic if unknown
    limits = PLAN_LIMITS.get(plan_key, PLAN_LIMITS["free"])

    return SubscriptionStatusResponse(
        email=email,
        plan=plan_key,
        max_documents=limits["max_documents"],
        max_chars=limits["max_chars"],
    )


# --------------------------------------------------
# Routes
# --------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr):
    """
    Called by Billing + Upload pages to discover the user's plan and limits.
    """
    status = get_plan_for_email(email)

    # If truly free + no customer at all, we can optionally return 404
    if status.plan == "free":
        # Return 200 with "free" or 404 depending on your preference.
        # Here we return 200 for simplicity so the frontend doesn't treat it as an error.
        return status

    return status


@app.post("/create-checkout-session")
async def create_checkout_session(req: CheckoutRequest):
    """
    Create a Stripe Checkout session for the chosen tier.
    """
    tier = req.tier.lower()
    plan_to_price = {
        "basic": PRICE_BASIC_ID,
        "pro": PRICE_PRO_ID,
        "enterprise": PRICE_ENTERPRISE_ID,
    }

    price_id = plan_to_price.get(tier)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown tier '{tier}'")

    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured on backend.")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=req.email,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{FRONTEND_URL}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/Billing?status=cancelled",
        )
    except Exception as e:
        logger.exception("Error creating Stripe Checkout session")
        raise HTTPException(status_code=500, detail=f"Error creating checkout session: {e}")

    return {"checkout_url": session.url}


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Stripe webhook endpoint.
    Currently we just validate the event and log it; plan checks are done live via the API.
    """
    if not STRIPE_WEBHOOK_SECRET:
        # If you haven't set up a webhook secret, just accept the event (useful for local dev).
        return {"status": "webhook disabled"}

    payload = await request.body()
    sig_header = stripe_signature or request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    logger.info(f"Received Stripe event: {event_type}")

    # You can add richer handling here if you want to log, store, or react to events
    # e.g. checkout.session.completed, customer.subscription.deleted, etc.

    return {"status": "ok"}


@app.post("/summarize")
async def summarize(req: SummarizeRequest):
    """
    Main summarization endpoint.

    Enforces per-plan character limits and calls OpenAI to generate a summary.
    """
    status = get_plan_for_email(req.email)
    limits = PLAN_LIMITS.get(status.plan, PLAN_LIMITS["free"])

    # Simple per-request character limit enforcement
    if req.char_count > limits["max_chars"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Your input is {req.char_count:,} characters, which exceeds the "
                f"maximum of {limits['max_chars']:,} for the {status.plan} plan."
            ),
        )

    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    prompt = (
        "You are an assistant that converts long reports or notes into clear, "
        "business-friendly summaries. Highlight:\n"
        "- Key themes and takeaways\n"
        "- Risks or issues\n"
        "- Action items and owners (if mentioned)\n\n"
        "Return a concise summary that a busy executive could read quickly."
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"Filename: {req.filename or 'N/A'}\n\nContent:\n{req.content}",
                },
            ],
            max_tokens=800,
        )
        summary = completion.choices[0].message.content
    except Exception as e:
        logger.exception("Error calling OpenAI")
        raise HTTPException(status_code=500, detail=f"Error generating summary: {e}")

    return {
        "email": req.email,
        "plan": status.plan,
        "summary": summary,
    }
