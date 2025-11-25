import os
import logging
from typing import Literal, Optional

import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

PRICE_BASIC = os.environ.get("PRICE_BASIC")          # e.g. price_123
PRICE_PRO = os.environ.get("PRICE_PRO")              # e.g. price_456
PRICE_ENTERPRISE = os.environ.get("PRICE_ENTERPRISE")  # e.g. price_789

FRONTEND_URL = os.environ.get(
    "FRONTEND_URL", "https://ai-report-saas.onrender.com"
).rstrip("/")

# Where Stripe should send users after checkout
SUCCESS_URL = f"{FRONTEND_URL}/Billing"
CANCEL_URL = os.environ.get("CANCEL_URL", f"{FRONTEND_URL}/Billing").rstrip("/")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set in the environment.")

if not PRICE_BASIC or not PRICE_PRO or not PRICE_ENTERPRISE:
    raise RuntimeError("PRICE_BASIC / PRICE_PRO / PRICE_ENTERPRISE must be set.")

stripe.api_key = STRIPE_SECRET_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook")

# ---------------------------------------------------------------------
# FastAPI app + CORS
# ---------------------------------------------------------------------

app = FastAPI(title="AI Report Backend", version="1.0.0")

origins = [
    FRONTEND_URL,
    FRONTEND_URL + "/",  # just in case
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    plan: Literal["basic", "pro", "enterprise"]
    email: EmailStr


class SubscriptionStatusRequest(BaseModel):
    email: EmailStr


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    active: bool
    plan: Literal["free", "basic", "pro", "enterprise"]
    upload_limit: int
    max_chars: int


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _plan_for_price_id(price_id: str) -> str:
    if price_id == PRICE_BASIC:
        return "basic"
    if price_id == PRICE_PRO:
        return "pro"
    if price_id == PRICE_ENTERPRISE:
        return "enterprise"
    return "free"


def _limits_for_plan(plan: str) -> tuple[int, int]:
    """
    Returns (upload_limit_per_month, max_chars_per_summary)
    Adjust these numbers however you like.
    """
    if plan == "basic":
        return 5, 8_000
    if plan == "pro":
        return 30, 20_000
    if plan == "enterprise":
        return 1_000, 50_000  # effectively unlimited
    # free
    return 2, 3_000


def _find_active_subscription_for_email(email: str) -> Optional[str]:
    """
    Look up the customer's active subscription plan in Stripe.
    Returns 'basic'/'pro'/'enterprise' or None if no active sub is found.
    """
    # 1. Find customers with this email
    customers = stripe.Customer.list(email=email, limit=5)
    if not customers.data:
        logger.info("No Stripe customers found for email %s", email)
        return None

    # 2. Look through each customer's subscriptions
    for customer in customers.data:
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=10,
            expand=["data.items.price"],
        )

        for sub in subs.data:
            if sub.status not in ("active", "trialing", "past_due"):
                continue

            # Use the first item’s price to decide the plan
            if not sub.items.data:
                continue

            price = sub.items.data[0].price
            plan = _plan_for_price_id(price.id)
            if plan != "free":
                logger.info(
                    "Found active subscription for %s: customer=%s, plan=%s",
                    email,
                    customer.id,
                    plan,
                )
                return plan

    logger.info("No active subscriptions found in Stripe for %s", email)
    return None


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/create-checkout-session")
def create_checkout_session(payload: CheckoutRequest):
    """
    Create a Stripe Checkout session for a SUBSCRIPTION plan.
    The frontend should POST:
    {
        "plan": "basic" | "pro" | "enterprise",
        "email": "user@example.com"
    }
    """

    plan_to_price = {
        "basic": PRICE_BASIC,
        "pro": PRICE_PRO,
        "enterprise": PRICE_ENTERPRISE,
    }

    price_id = plan_to_price.get(payload.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Unknown plan requested.")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",  # <-- subscription mode
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            # NOTE: DO NOT set `customer_creation` in subscription mode
            customer_email=payload.email,
            success_url=f"{SUCCESS_URL}?status=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{CANCEL_URL}?status=cancelled",
            allow_promotion_codes=True,
            subscription_data={
                "metadata": {
                    "email": payload.email,
                    "plan": payload.plan,
                }
            },
        )
        logger.info(
            "Created checkout session %s for email=%s plan=%s",
            session.id,
            payload.email,
            payload.plan,
        )
        return {"checkout_url": session.url}
    except stripe.error.StripeError as e:
        logger.exception("Stripe error while creating checkout session")
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error: {str(e)}",
        )
    except Exception as e:
        logger.exception("Unexpected error while creating checkout session")
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while creating checkout session.",
        ) from e


@app.post("/subscription-status", response_model=SubscriptionStatusResponse)
def subscription_status(payload: SubscriptionStatusRequest):
    """
    Check the user's current subscription by email directly in Stripe.
    Frontend should POST:
    { "email": "user@example.com" }
    """
    email = payload.email

    try:
        plan = _find_active_subscription_for_email(email)
    except stripe.error.StripeError as e:
        logger.exception("Stripe error while checking subscription")
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error while checking subscription: {str(e)}",
        )

    if plan is None:
        plan = "free"

    upload_limit, max_chars = _limits_for_plan(plan)

    return SubscriptionStatusResponse(
        email=email,
        active=(plan != "free"),
        plan=plan,  # 'free' | 'basic' | 'pro' | 'enterprise'
        upload_limit=upload_limit,
        max_chars=max_chars,
    )


@app.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint.
    For now we just verify the signature and log events.
    You can expand this later to sync data into a DB if you want.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        # If you haven't configured a webhook secret yet,
        # just log and return 200 so Stripe doesn't complain.
        logger.warning("STRIPE_WEBHOOK_SECRET not set; skipping verification.")
        try:
            event = stripe.Event.construct_from(
                {"type": "unknown", "data": {"object": {}}}, stripe.api_key
            )
        except Exception:
            event = None
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except stripe.error.SignatureVerificationError:
            logger.exception("Invalid Stripe webhook signature.")
            raise HTTPException(status_code=400, detail="Invalid signature")

    if event:
        logger.info("Received Stripe event: %s", event["type"])

    # You can expand this block to react to specific events if you want
    # (checkout.session.completed, customer.subscription.updated, etc.)
    return {"received": True}
