import os
import logging
from typing import Optional

import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-report-backend")

# -------------------------------------------------------------------
# Environment / Stripe config
# -------------------------------------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

STRIPE_PRICE_BASIC = os.environ.get("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_ENTERPRISE = os.environ.get("STRIPE_PRICE_ENTERPRISE", "")

FRONTEND_URL = (os.environ.get("FRONTEND_URL") or "").rstrip("/")
SUCCESS_URL = os.environ.get(
    "SUCCESS_URL",
    f"{FRONTEND_URL}/Billing?status=success",
)
CANCEL_URL = f"{FRONTEND_URL}/Billing?status=cancelled"

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logger.warning("STRIPE_SECRET_KEY is not set; billing endpoints will fail.")

PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

# -------------------------------------------------------------------
# FastAPI app
# -------------------------------------------------------------------
app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten if you want later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------
class CheckoutRequest(BaseModel):
    plan: str
    email: EmailStr


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    has_active_subscription: bool
    plan: Optional[str] = None
    current_period_end: Optional[int] = None  # Unix timestamp (seconds)


# -------------------------------------------------------------------
# Health check
# -------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# -------------------------------------------------------------------
# Create Checkout Session
# -------------------------------------------------------------------
@app.post("/create-checkout-session")
async def create_checkout_session(payload: CheckoutRequest):
    """
    Create a Stripe Checkout Session for a subscription.

    Frontend sends:
      { "plan": "basic" | "pro" | "enterprise", "email": "user@example.com" }

    We allow promotion codes on the Stripe Checkout page itself.
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    price_id = PLAN_TO_PRICE.get(payload.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan selected")

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
            success_url=SUCCESS_URL + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=CANCEL_URL,
            allow_promotion_codes=True,  # user can enter a coupon on checkout
        )

        logger.info(
            "Created checkout session %s for plan %s and email %s",
            session.id,
            payload.plan,
            payload.email,
        )

        # Return both keys so the Billing page works regardless of which one it uses
        return {
            "checkout_url": session.url,  # previous style
            "url": session.url,           # commonly expected key in many examples
            "id": session.id,
        }
    except Exception as e:
        logger.exception("Error creating checkout session: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to create checkout session"
        )


# -------------------------------------------------------------------
# Stripe Webhook
# -------------------------------------------------------------------
@app.post("/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured.")
        raise HTTPException(
            status_code=500, detail="Webhook secret is not configured"
        )

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
        logger.exception("Invalid payload sent to Stripe webhook")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        logger.exception("Invalid signature on Stripe webhook")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data_object = event["data"]["object"]

    logger.info("Received Stripe webhook event type=%s", event_type)

    if event_type == "checkout.session.completed":
        email = data_object.get("customer_email")
        subscription_id = data_object.get("subscription")
        logger.info(
            "Checkout session completed for %s, subscription %s",
            email,
            subscription_id,
        )
        # You could add any post-checkout logic here.
    elif event_type == "customer.subscription.deleted":
        logger.info(
            "Subscription %s cancelled for customer %s",
            data_object.get("id"),
            data_object.get("customer"),
        )
    else:
        # For now we just log other event types
        logger.debug("Unhandled Stripe event type: %s", event_type)

    return {"received": True}


# -------------------------------------------------------------------
# Subscription Status
# -------------------------------------------------------------------
@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr):
    """
    Look up subscription status for a given email.

    Returns whether there is any active (or recently active) subscription
    and basic info about it.
    """
    if not STRIPE_SECRET_KEY:
        # Just say "no active sub" instead of throwing, to keep the UI simple.
        logger.error("Cannot check subscription status: STRIPE_SECRET_KEY not set")
        return SubscriptionStatusResponse(
            email=email,
            has_active_subscription=False,
        )

    try:
        # 1) Find customer by email
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return SubscriptionStatusResponse(
                email=email,
                has_active_subscription=False,
            )

        customer = customers.data[0]

        # 2) Get most recent subscription for that customer (any status)
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=1,
        )
        if not subs.data:
            return SubscriptionStatusResponse(
                email=email,
                has_active_subscription=False,
            )

        sub = subs.data[0]
        status = sub.status

        # Treat these as "has a subscription"
        has_active = status in ("trialing", "active", "past_due", "unpaid")

        # Try to extract a human-readable plan name
        plan_name: Optional[str] = None
        try:
            if sub.items and sub.items.data:
                price = sub.items.data[0].price
                # Prefer nickname (e.g., "Basic", "Pro", "Enterprise")
                plan_name = price.nickname or price.id
        except Exception:
            plan_name = None

        # Use dict-style access so we don't crash if the key is missing
        current_period_end = sub.get("current_period_end")

        return SubscriptionStatusResponse(
            email=email,
            has_active_subscription=has_active,
            plan=plan_name,
            current_period_end=current_period_end,
        )
    except Exception as e:
        logger.exception("Error looking up subscription status: %s", e)
        # On error, just report "no active subscription" to keep the UI stable
        return SubscriptionStatusResponse(
            email=email,
            has_active_subscription=False,
        )
