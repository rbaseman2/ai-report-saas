import os
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import JSONResponse

import stripe
from openai import OpenAI

# ---------------------------------------------------------
# Environment / config helpers
# ---------------------------------------------------------

# Stripe API key (required)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set in the environment.")

stripe.api_key = STRIPE_SECRET_KEY

# Frontend base URL (for redirect after checkout)
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

# Success / cancel URLs for Stripe checkout
CHECKOUT_SUCCESS_URL = os.getenv(
    "CHECKOUT_SUCCESS_URL",
    f"{FRONTEND_URL}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}",
)
CHECKOUT_CANCEL_URL = os.getenv(
    "CHECKOUT_CANCEL_URL",
    f"{FRONTEND_URL}/Billing?status=cancel",
)

# Price IDs – support both old and new naming schemes
def _env_price(*keys: str) -> Optional[str]:
    for k in keys:
        v = os.getenv(k)
        if v:
            return v
    return None


PLAN_PRICE_IDS = {
    "basic": _env_price("STRIPE_BASIC_PRICE_ID", "PRICE_BASIC"),
    "pro": _env_price("STRIPE_PRO_PRICE_ID", "PRICE_PRO"),
    "enterprise": _env_price("STRIPE_ENTERPRISE_PRICE_ID", "PRICE_ENTERPRISE"),
}

# Character limits per plan
PLAN_LIMITS = {
    "free": 20000,
    "basic": 40000,
    "pro": 100000,
    "enterprise": 250000,
}

# Map price_id -> plan slug (used when checking subscription)
PRICE_TO_PLAN = {
    pid: plan for plan, pid in PLAN_PRICE_IDS.items() if pid is not None
}

# OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set in the environment.")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------

app = FastAPI(title="AI Report Backend")

# Allow Streamlit frontend to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can tighten this later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------

PlanName = Literal["free", "basic", "pro", "enterprise"]


class CheckoutRequest(BaseModel):
    plan: Literal["basic", "pro", "enterprise"]
    email: str


class CheckoutResponse(BaseModel):
    checkout_url: str


class SummarizeRequest(BaseModel):
    text: str
    email: Optional[str] = None  # optional – if missing, treated as "free"


class SummarizeResponse(BaseModel):
    plan: PlanName
    used_chars: int
    max_chars: int
    summary: str


class SubscriptionStatusResponse(BaseModel):
    email: str
    plan: PlanName
    status: Literal["none", "active", "inactive"]


# ---------------------------------------------------------
# Helper functions
# ---------------------------------------------------------


def get_price_id_for_plan(plan: str) -> str:
    price_id = PLAN_PRICE_IDS.get(plan)
    if not price_id:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Stripe price ID not configured for plan '{plan}'. "
                f"Set STRIPE_{plan.upper()}_PRICE_ID or PRICE_{plan.upper()} "
                f"in the environment."
            ),
        )
    return price_id


def get_plan_for_email(email: Optional[str]) -> PlanName:
    """
    Look up the active subscription for a given email in Stripe.

    Returns: "basic" | "pro" | "enterprise" | "free"
    """
    if not email:
        return "free"

    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return "free"

        customer = customers.data[0]

        # Fetch most recent subscription for this customer
        subs = stripe.Subscription.list(customer=customer.id, status="all", limit=1)
        if not subs.data:
            return "free"

        sub = subs.data[0]
        status = sub.status  # e.g. "active", "trialing", "canceled"

        if status not in ("active", "trialing", "past_due", "unpaid"):
            # treat everything else as inactive/free
            return "free"

        # Get the first price ID from subscription items
        items = sub["items"]["data"]
        if not items:
            return "free"

        price_id = items[0]["price"]["id"]
        plan = PRICE_TO_PLAN.get(price_id)

        return plan if plan in ("basic", "pro", "enterprise") else "free"

    except Exception as exc:
        # Fail open as "free" but log details to help debugging
        print(f"[subscription-status] Error while checking subscription for {email}: {exc}")
        return "free"


def summarize_text_for_plan(
    text: str, plan: PlanName, email: Optional[str] = None
) -> SummarizeResponse:
    max_chars = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    trimmed = text[:max_chars]

    system_prompt = (
        "You are an AI assistant that creates concise, business-friendly summaries.\n"
        "The user will provide a long report, document, or notes. Your job is to:\n"
        "1) Extract key insights, decisions, risks, and action items.\n"
        "2) Write in clear, plain business language (no medical or clinical framing).\n"
        "3) Organize the output with headings and bullet points where helpful.\n"
        "4) Assume the reader is a non-technical client or business stakeholder."
    )

    user_prompt = (
        "Summarize the following content for a business audience. "
        "Focus on what matters for decision-making, next steps, and communication "
        "to clients or internal stakeholders.\n\n"
        f"{trimmed}"
    )

    resp = openai_client.responses.create(
        model="gpt-4.1-mini",
        temperature=0.4,
        max_output_tokens=1200,
        system=system_prompt,
        input=user_prompt,
    )

    # Extract the text from the new Responses API
    try:
        summary_text = resp.output[0].content[0].text
    except Exception:
        # Fallback in case structure changes
        summary_text = str(resp)

    return SummarizeResponse(
        plan=plan,
        used_chars=len(trimmed),
        max_chars=max_chars,
        summary=summary_text,
    )


# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(payload: CheckoutRequest):
    """
    Create a Stripe Checkout session for a subscription plan.

    Body:
    {
        "plan": "basic" | "pro" | "enterprise",
        "email": "user@example.com"
    }
    """
    plan = payload.plan
    email = payload.email.strip().lower()

    price_id = get_price_id_for_plan(plan)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_creation="if_required",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=CHECKOUT_SUCCESS_URL,
            cancel_url=CHECKOUT_CANCEL_URL,
            customer_email=email,
            allow_promotion_codes=True,  # enable coupon entry
            subscription_data={
                "metadata": {
                    "plan": plan,
                    "email": email,
                }
            },
        )
        return CheckoutResponse(checkout_url=session.url)
    except stripe.error.StripeError as e:
        # Stripe-related error
        print(f"[create-checkout-session] Stripe error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error while creating checkout session: {str(e)}",
        )
    except Exception as e:
        print(f"[create-checkout-session] Unexpected error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while creating checkout session.",
        )


@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: str = Query(..., description="Subscriber email")):
    """
    Check the user's active subscription plan by email.
    Used by the front-end Upload_Data page to decide limits.
    """
    email_normalized = email.strip().lower()
    plan = get_plan_for_email(email_normalized)

    status: Literal["none", "active", "inactive"]
    if plan == "free":
        status = "none"
    else:
        status = "active"

    return SubscriptionStatusResponse(email=email_normalized, plan=plan, status=status)


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(payload: SummarizeRequest):
    """
    Summarize a block of text for a business audience.

    Body:
    {
        "text": "...",
        "email": "user@example.com"   # optional, used to look up plan
    }
    """
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="Text is required for summarization.")

    # Determine plan based on email (or default to free)
    plan = get_plan_for_email(payload.email)

    try:
        result = summarize_text_for_plan(payload.text, plan, payload.email)
        return result
    except Exception as e:
        print(f"[summarize] Error while generating summary: {e}")
        raise HTTPException(status_code=500, detail="Error while generating summary.")


# Root just shows basic info
@app.get("/")
async def root():
    return {
        "service": "ai-report-backend",
        "endpoints": [
            "/health",
            "/create-checkout-session",
            "/subscription-status",
            "/summarize",
        ],
    }
