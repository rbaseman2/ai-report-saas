# server/webhook.py

import os
from typing import Literal, Optional

import stripe
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------- Env & Stripe setup ----------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Price IDs for your 3 plans
PRICE_BASIC_ID = os.getenv("PRICE_BASIC")
PRICE_PRO_ID = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE_ID = os.getenv("PRICE_ENTERPRISE")

PLAN_PRICE_IDS = {
    "basic": PRICE_BASIC_ID,
    "pro": PRICE_PRO_ID,
    "enterprise": PRICE_ENTERPRISE_ID,
}

# Frontend base URL – used in success / cancel URLs
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

# ---------- FastAPI app & CORS ----------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can restrict this later to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Models ----------


class CheckoutRequest(BaseModel):
    plan: Literal["basic", "pro", "enterprise"]
    email: str
    # Optional: if you ever want to pre-attach a coupon,
    # you could use this field; currently we just rely on
    # Stripe's promotion code UI.
    coupon_code: Optional[str] = None


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusRequest(BaseModel):
    email: str


class SubscriptionStatusResponse(BaseModel):
    email: str
    status: Literal["free", "basic", "pro", "enterprise"]
    plan: Optional[str] = None
    # You can extend this payload with upload limits, etc.
    max_documents_per_month: int
    description: str


class SummarizeRequest(BaseModel):
    text: str
    max_words: Optional[int] = 400
    audience: Optional[str] = "business stakeholders and clients"


class SummarizeResponse(BaseModel):
    summary: str


# ---------- Health check ----------

# Root – handy if you just hit the backend in a browser.
@app.get("/")
async def root():
    return {"status": "ok", "endpoint": "root"}


# Explicit /health route for Render & other probes.
@app.get("/health")
async def health():
    return {"status": "ok", "endpoint": "health"}

# ---------- Stripe: create checkout session ----------


@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(payload: CheckoutRequest):
    """
    Create a Stripe Checkout session for a subscription plan.

    Frontend should POST:
    {
        "plan": "basic" | "pro" | "enterprise",
        "email": "user@example.com"
    }
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured. Missing STRIPE_SECRET_KEY.",
        )

    price_id = PLAN_PRICE_IDS.get(payload.plan)
    if not price_id:
        raise HTTPException(
            status_code=500,
            detail=f"Stripe price ID not configured for plan '{payload.plan}'. "
            f"Set PRICE_{payload.plan.upper()} in the environment.",
        )

    try:
        # URL where the user lands after completing checkout
        success_url = (
            f"{FRONTEND_URL}/Billing"
            "?status=success&session_id={{CHECKOUT_SESSION_ID}}"
        )
        # URL if they cancel from the checkout page
        cancel_url = f"{FRONTEND_URL}/Billing?status=cancelled"

        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=payload.email,
            # Show "Have a promo code?" box on Stripe page
            allow_promotion_codes=True,
            # DO NOT pass customer_creation here – that is only for mode="payment"
        )

        return CheckoutResponse(checkout_url=session.url)

    except stripe.error.StripeError as e:
        # Bubble a friendly error up to the UI
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error while creating checkout session: {str(e)}",
        )


# ---------- Stripe: check subscription status ----------


def _map_price_to_plan(price_id: str) -> str:
    """Map a Stripe price ID back to a friendly plan name."""
    if price_id == PRICE_BASIC_ID:
        return "basic"
    if price_id == PRICE_PRO_ID:
        return "pro"
    if price_id == PRICE_ENTERPRISE_ID:
        return "enterprise"
    return "unknown"


def _plan_limits(plan: str) -> tuple[int, str]:
    """Return (max_documents_per_month, description) for each plan."""
    if plan == "basic":
        return 5, "Upload up to 5 documents per month."
    if plan == "pro":
        return 30, "Upload up to 30 documents per month."
    if plan == "enterprise":
        return 10_000, "Unlimited uploads for your team (practical upper bound)."
    # free fallback
    return 2, "Free plan: limited uploads and shorter summaries."


@app.post(
    "/subscription-status", response_model=SubscriptionStatusResponse
)
async def subscription_status(
    payload: SubscriptionStatusRequest,
):
    """
    Check the current subscription status for a given email.

    Frontend POST body:
    { "email": "user@example.com" }
    """
    email = payload.email.strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")

    if not STRIPE_SECRET_KEY:
        # If Stripe isn't configured, just treat everyone as free
        max_docs, desc = _plan_limits("free")
        return SubscriptionStatusResponse(
            email=email,
            status="free",
            plan=None,
            max_documents_per_month=max_docs,
            description=desc,
        )

    try:
        # 1) Find customer by email
        customers = stripe.Customer.list(email=email, limit=1).data
        if not customers:
            max_docs, desc = _plan_limits("free")
            return SubscriptionStatusResponse(
                email=email,
                status="free",
                plan=None,
                max_documents_per_month=max_docs,
                description=desc,
            )

        customer = customers[0]

        # 2) Find their first ACTIVE subscription
        subs = stripe.Subscription.list(
            customer=customer.id, status="active", limit=1
        ).data

        if not subs:
            max_docs, desc = _plan_limits("free")
            return SubscriptionStatusResponse(
                email=email,
                status="free",
                plan=None,
                max_documents_per_month=max_docs,
                description=desc,
            )

        sub = subs[0]
        if not sub["items"]["data"]:
            max_docs, desc = _plan_limits("free")
            return SubscriptionStatusResponse(
                email=email,
                status="free",
                plan=None,
                max_documents_per_month=max_docs,
                description=desc,
            )

        price = sub["items"]["data"][0]["price"]
        price_id = price["id"]
        plan = _map_price_to_plan(price_id)

        if plan == "unknown":
            # Treat unknown price as free but include a note
            max_docs, desc = _plan_limits("free")
            desc = (
                desc
                + " (We detected an active Stripe subscription, "
                "but the price ID isn't mapped to a plan.)"
            )
            return SubscriptionStatusResponse(
                email=email,
                status="free",
                plan=None,
                max_documents_per_month=max_docs,
                description=desc,
            )

        max_docs, desc = _plan_limits(plan)
        return SubscriptionStatusResponse(
            email=email,
            status=plan,  # "basic", "pro", or "enterprise"
            plan=plan,
            max_documents_per_month=max_docs,
            description=desc,
        )

    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error while checking subscription: {str(e)}",
        )


# ---------- OpenAI summarization ----------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

try:
    # Use the official OpenAI client if available
    from openai import OpenAI

    openai_client: Optional["OpenAI"] = (
        OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
    )
except Exception:  # pragma: no cover - fail gracefully if library missing
    openai_client = None


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(payload: SummarizeRequest):
    """
    Turn a long document into a concise, business-friendly summary.
    """
    if not openai_client:
        raise HTTPException(
            status_code=500,
            detail="OpenAI is not configured. Set OPENAI_API_KEY in the environment.",
        )

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required for summarization.")

    max_words = payload.max_words or 400

    # Construct a clear system prompt
    system_prompt = (
        "You are an assistant that writes clear, business-friendly summaries of long "
        "documents. Highlight key points, risks, decisions, and next steps. "
        f"Write for an audience of {payload.audience}. "
        f"Keep the summary under about {max_words} words."
    )

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Please summarize the following document:\n\n" + text
                    ),
                },
            ],
        )

        summary_text = completion.choices[0].message.content.strip()
        return SummarizeResponse(summary=summary_text)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error while generating summary: {str(e)}",
        )
