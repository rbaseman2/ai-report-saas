# server/webhook.py

import os
import logging
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import stripe

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-report-backend")

# -----------------------------------------------------------------------------
# Environment configuration
# -----------------------------------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Price IDs for each plan
PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

# Where Stripe should send users back after checkout
FRONTEND_BILLING_URL = os.getenv(
    "FRONTEND_BILLING_URL",
    "https://ai-report-saas.onrender.com/Billing",
)

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY is not set – Stripe calls will fail.")

stripe.api_key = STRIPE_SECRET_KEY

# -----------------------------------------------------------------------------
# FastAPI setup
# -----------------------------------------------------------------------------
app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later if you want
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------
PlanName = Literal["basic", "pro", "enterprise"]


class CheckoutSessionRequest(BaseModel):
    plan: PlanName
    email: EmailStr


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    plan: Optional[PlanName] = None
    status: Literal["none", "active", "incomplete", "canceled"] = "none"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def get_price_id_for_plan(plan: PlanName) -> str:
    if plan == "basic":
        pid = PRICE_BASIC
    elif plan == "pro":
        pid = PRICE_PRO
    else:  # "enterprise"
        pid = PRICE_ENTERPRISE

    if not pid:
        logger.error(f"No Stripe price ID configured for plan '{plan}'")
        raise HTTPException(
            status_code=500,
            detail=f"Stripe price ID not configured for plan '{plan}'. "
                   f"Set PRICE_{plan.upper()} in the environment.",
        )
    return pid


def build_success_url() -> str:
    """
    Billing page URL with placeholders for Stripe's session ID.
    Stripe will replace {CHECKOUT_SESSION_ID} automatically.
    """
    base = FRONTEND_BILLING_URL.rstrip("/")
    return f"{base}?status=success&session_id={{CHECKOUT_SESSION_ID}}"


def build_cancel_url() -> str:
    base = FRONTEND_BILLING_URL.rstrip("/")
    return f"{base}?status=cancelled"


def get_active_subscription_for_email(email: str) -> SubscriptionStatusResponse:
    """
    Look up the active subscription for a given email via Stripe.
    No local DB required for now.
    """
    try:
        customers = stripe.Customer.list(email=email, limit=1)
    except Exception as exc:
        logger.exception("Error looking up Stripe customer for %s", email)
        raise HTTPException(status_code=500, detail=str(exc))

    if not customers.data:
        # No Stripe customer at all for this email
        return SubscriptionStatusResponse(email=email, status="none", plan=None)

    customer = customers.data[0]

    try:
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=5,
        )
    except Exception as exc:
        logger.exception("Error listing Stripe subscriptions for %s", email)
        raise HTTPException(status_code=500, detail=str(exc))

    if not subs.data:
        return SubscriptionStatusResponse(email=email, status="none", plan=None)

    # Pick the most relevant subscription (usually the latest one)
    sub = subs.data[0]
    status = sub.status or "none"

    # Get the price ID for the first subscription item
    price_id = None
    if sub.items.data:
        price_id = sub.items.data[0].price.id

    plan: Optional[PlanName] = None
    if price_id == PRICE_BASIC:
        plan = "basic"
    elif price_id == PRICE_PRO:
        plan = "pro"
    elif price_id == PRICE_ENTERPRISE:
        plan = "enterprise"

    return SubscriptionStatusResponse(email=email, status=status, plan=plan)


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/create-checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout_session(payload: CheckoutSessionRequest):
    """
    Create a Stripe Checkout Session for a subscription plan.

    The frontend should POST JSON:
    {
        "plan": "basic" | "pro" | "enterprise",
        "email": "user@example.com"
    }
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe secret key not configured on the backend.",
        )

    price_id = get_price_id_for_plan(payload.plan)
    success_url = build_success_url()
    cancel_url = build_cancel_url()

    logger.info(
        "Creating checkout session: plan=%s, email=%s",
        payload.plan,
        payload.email,
    )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            customer_email=payload.email,
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,  # <-- enables coupon/promo code box
            metadata={
                "plan": payload.plan,
            },
        )
    except Exception as exc:
        logger.exception("Error creating Stripe checkout session")
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error creating checkout session: {exc}",
        )

    return CheckoutSessionResponse(checkout_url=session.url)


@app.get("/subscription", response_model=SubscriptionStatusResponse)
async def get_subscription(email: EmailStr):
    """
    Check the current subscription status for a given email.

    Frontend usage example (Streamlit):
      requests.get(f"{BACKEND_URL}/subscription", params={"email": email})

    Returns 200 with status & plan, even if status is "none".
    """
    status = get_active_subscription_for_email(email)

    # We always return 200 here, even if there is no plan or an inactive one.
    # The frontend can treat status=="none" as "Free plan".
    return status


@app.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint.
    For now we just verify the signature and log the event.
    """
    if not STRIPE_WEBHOOK_SECRET:
        logger.warning("STRIPE_WEBHOOK_SECRET not set; webhook not verified.")
        # You can still parse the JSON, but it's less secure.
        data = await request.json()
        logger.info("Received (unverified) Stripe webhook event: %s", data)
        return {"received": True, "verified": False}

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        # Invalid payload
        logger.exception("Invalid payload in Stripe webhook")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        logger.exception("Invalid Stripe webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Log event type; you can extend this to update your own DB if you add one.
    logger.info("Received Stripe event: %s", event["type"])

    # Example: when an invoice is paid or subscription updated, you could
    # sync local records here.

    return {"received": True, "verified": True}
