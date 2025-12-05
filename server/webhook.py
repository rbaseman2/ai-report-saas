# server/webhook.py

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import stripe
from openai import OpenAI

# -------------------------------------------------------------------
# Environment / config
# -------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_BASIC_ID = os.getenv("PRICE_BASIC")        # e.g. price_123
PRICE_PRO_ID = os.getenv("PRICE_PRO")            # e.g. price_456
PRICE_ENTERPRISE_ID = os.getenv("PRICE_ENTERPRISE")

# Frontend redirect URLs (you already set these on Render)
SUCCESS_URL = os.getenv("SUCCESS_URL")           # e.g. https://ai-report-saas.onrender.com/Billing?status=success
CANCEL_URL = os.getenv("CANCEL_URL")             # e.g. https://ai-report-saas.onrender.com/Billing?status=canceled

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY
openai_client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()

# Allow Streamlit frontend to talk to backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later if you like
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Helpers
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
    # unknown price → treat as Free to be safe
    return DEFAULT_LIMITS


def get_limits_for_email(email: str) -> PlanLimits:
    """
    Look up the active Stripe subscription for this email and return the
    corresponding limits. If nothing active, return Free limits.
    """
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
        # Assume first item controls the plan
        item = sub["items"]["data"][0]
        price_id = item["price"]["id"]
        return _map_price_to_limits(price_id)
    except Exception:
        # On any Stripe error, fail open as Free
        return DEFAULT_LIMITS


# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan: str   # "basic" | "pro" | "enterprise"
    email: str


class SummarizeRequest(BaseModel):
    email: str
    text: str


class SummarizeResponse(BaseModel):
    summary: str
    plan: str
    max_chars: int
    used_chars: int


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/subscription-status")
async def subscription_status(email: str):
    """
    Returns the current plan & limits for a given email.
    Used by BOTH Billing page and Upload page.
    """
    limits = get_limits_for_email(email)
    return limits.model_dump()


@app.post("/create-checkout-session")
async def create_checkout_session(req: CheckoutRequest):
    """
    Creates a Stripe Checkout Session for a subscription.
    """
    plan = req.plan.lower()
    email = req.email.strip()

    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    if plan == "basic":
        price_id = PRICE_BASIC_ID
    elif plan == "pro":
        price_id = PRICE_PRO_ID
    elif plan == "enterprise":
        price_id = PRICE_ENTERPRISE_ID
    else:
        raise HTTPException(status_code=400, detail="Unknown plan")

    if not price_id:
        raise HTTPException(
            status_code=500,
            detail=f"PRICE id not configured for plan {plan}.",
        )

    if not SUCCESS_URL or not CANCEL_URL:
        raise HTTPException(
            status_code=500,
            detail="SUCCESS_URL and CANCEL_URL must be set in the backend environment.",
        )

    try:
        # You can choose whether SUCCESS_URL already has query params.
        # Here we just always append the session id as ?session_id=...
        success_url = f"{SUCCESS_URL}&session_id={{CHECKOUT_SESSION_ID}}" if "?" in SUCCESS_URL \
            else f"{SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}"

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=email,  # pre-fills email
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=CANCEL_URL,

            # ✅ This shows the “Add promotion code” box
            allow_promotion_codes=True,

            # Optional nice-to-haves:
            billing_address_collection="auto",
            phone_number_collection={"enabled": True},
        )

        return {"checkout_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest):
    """
    Generates a business-friendly summary of the uploaded content.
    Enforces length limits based on the user's subscription.
    """
    email = req.email.strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    limits = get_limits_for_email(email)
    max_chars = limits.max_chars

    # Trim text to max_chars and also put a hard safety cap
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
                        "You are an AI assistant that turns long, dense reports into a concise, "
                        "business-friendly summary for executives and stakeholders. "
                        "Highlight key points, risks, action items, and recommendations."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.4,
        )

        summary = completion.choices[0].message.content.strip()
        return SummarizeResponse(
            summary=summary,
            plan=limits.plan,
            max_chars=max_chars,
            used_chars=used,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------
# Stripe webhook (optional, but kept if you already configured it)
# -------------------------------------------------------------------

@app.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
):
    if STRIPE_WEBHOOK_SECRET is None:
        # If you haven't configured a webhook, just ignore calls
        return {"status": "no-webhook-configured"}

    payload = await request.body()
    sig_header = stripe_signature

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # You can add handling for specific events here if desired.
    # For now we just acknowledge.
    return {"status": "ok"}
