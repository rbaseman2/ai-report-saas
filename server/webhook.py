import logging
import os
from datetime import datetime, timezone
from typing import Literal, Optional

import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# ------------------------------------------------------------------------------
# Config & Stripe setup
# ------------------------------------------------------------------------------

logger = logging.getLogger("ai-report-backend")
logging.basicConfig(level=logging.INFO)

STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

STRIPE_PRICE_BASIC = os.environ.get("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = os.environ.get("STRIPE_PRICE_ENTERPRISE")

# optional: coupon id for a "welcome" code, e.g. env STRIPE_COUPON_WELCOME
STRIPE_COUPON_WELCOME = os.environ.get("STRIPE_COUPON_WELCOME")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://ai-report-saas.onrender.com")

# Where Stripe will send the user after checkout
SUCCESS_URL = os.environ.get(
    "SUCCESS_URL",
    f"{FRONTEND_URL}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}",
)
CANCEL_URL = os.environ.get(
    "CANCEL_URL",
    f"{FRONTEND_URL}/Billing?status=cancelled",
)

stripe.api_key = STRIPE_SECRET_KEY

PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

COUPON_MAP = {
    # billing coupon code (lowercase) -> Stripe coupon id
    "welcome": STRIPE_COUPON_WELCOME,
}


# ------------------------------------------------------------------------------
# FastAPI app
# ------------------------------------------------------------------------------

app = FastAPI(title="AI Report Backend")

# Allow Streamlit frontend to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        FRONTEND_URL.replace("https://", "http://"),
        "http://localhost:8501",
        "http://localhost:8502",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ------------------------------------------------------------------------------
# Models
# ------------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: Literal["basic", "pro", "enterprise"]
    # Optional coupon the user typed into the Billing page (e.g. "welcome")
    coupon_code: Optional[str] = None


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    status: str
    plan: Optional[str] = None
    current_period_end: Optional[datetime] = None


# ------------------------------------------------------------------------------
# Create Checkout Session
# ------------------------------------------------------------------------------

@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(payload: CheckoutRequest) -> CheckoutResponse:
    logger.info(
        "Creating checkout session for email=%s, plan=%s, coupon_code=%s",
        payload.email,
        payload.plan,
        payload.coupon_code,
    )

    price_id = PLAN_TO_PRICE.get(payload.plan)
    if not price_id:
        logger.error("Unknown plan %s", payload.plan)
        raise HTTPException(status_code=400, detail="Unknown plan")

    # Base params for all sessions
    session_params: dict = {
        "mode": "subscription",
        "success_url": SUCCESS_URL,
        "cancel_url": CANCEL_URL,
        "customer_email": payload.email,
        "line_items": [
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
    }

    # Coupon handling:
    # - If the Billing page sends a known coupon code, we auto-apply it
    #   via `discounts` (no coupon box needed on the Stripe page).
    # - Otherwise, we enable `allow_promotion_codes=True` so the Stripe
    #   checkout page shows the coupon / promotion code box and the user
    #   can enter any valid code there.
    coupon_code = (payload.coupon_code or "").strip().lower() or None
    if coupon_code:
        coupon_id = COUPON_MAP.get(coupon_code)
        if coupon_id:
            session_params["discounts"] = [{"coupon": coupon_id}]
            logger.info("Applying coupon %s (%s) to checkout session", coupon_code, coupon_id)
        else:
            # Unknown coupon -> still allow user to type something at checkout
            session_params["allow_promotion_codes"] = True
            logger.info("Unknown coupon code '%s'; falling back to promotion box", coupon_code)
    else:
        session_params["allow_promotion_codes"] = True

    try:
        session = stripe.checkout.Session.create(**session_params)
    except stripe.error.StripeError as e:
        logger.exception("Stripe error creating checkout session")
        raise HTTPException(status_code=500, detail=str(e)) from e

    logger.info(
        "Created checkout session %s for plan %s and email %s",
        session.id,
        payload.plan,
        payload.email,
    )
    return CheckoutResponse(checkout_url=session.url)


# ------------------------------------------------------------------------------
# Stripe Webhook
# ------------------------------------------------------------------------------

@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            logger.exception("Invalid Stripe webhook signature")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # If you haven't configured a webhook secret yet, treat raw payload as event
        logger.warning("STRIPE_WEBHOOK_SECRET not set, skipping verification")
        try:
            event = stripe.Event.construct_from(request.json(), stripe.api_key)
        except Exception:
            logger.exception("Failed to parse webhook payload")
            raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event["type"]
    logger.info("Received Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        logger.info(
            "Checkout session completed: id=%s email=%s",
            session.get("id"),
            session.get("customer_details", {}).get("email"),
        )
        # You could add additional business logic here (e.g. logging, DB update)

    elif event_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        logger.info(
            "Subscription deleted: id=%s customer=%s status=%s",
            sub.get("id"),
            sub.get("customer"),
            sub.get("status"),
        )
        # Again, hook to your persistence layer if needed.

    return {"received": True}


# ------------------------------------------------------------------------------
# Subscription Status
# ------------------------------------------------------------------------------

@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr) -> SubscriptionStatusResponse:
    """
    Return high-level subscription status for the given billing email.

    Handles the case where Stripe has multiple customers with the same email
    (from past tests) by scanning all of them and picking the newest
    non-canceled subscription.
    """
    logger.info("Looking up subscription status for %s", email)

    try:
        # Get up to 10 customers with this email
        customers = stripe.Customer.list(email=email, limit=10)
        if not customers.data:
            return SubscriptionStatusResponse(email=email, status="none")

        best_sub = None

        # Look at each customer and see if they have a subscription
        for customer in customers.data:
            subs = stripe.Subscription.list(
                customer=customer.id,
                status="all",
                limit=5,
            )
            for sub in subs.data:
                # Ignore fully canceled subscriptions
                if sub.status == "canceled":
                    continue
                # Keep the newest subscription we see
                if best_sub is None or sub.created > best_sub.created:
                    best_sub = sub

        if not best_sub:
            # No non-canceled subscription found on any customer
            return SubscriptionStatusResponse(email=email, status="none")

        sub = best_sub
        raw_status = getattr(sub, "status", "unknown") or "unknown"

        # Figure out plan name from price id
        items = getattr(sub, "items", None)
        plan_name: Optional[str] = None
        if items and getattr(items, "data", None):
            price = items.data[0].price
            price_id = getattr(price, "id", None)
            if price_id == STRIPE_PRICE_BASIC:
                plan_name = "basic"
            elif price_id == STRIPE_PRICE_PRO:
                plan_name = "pro"
            elif price_id == STRIPE_PRICE_ENTERPRISE:
                plan_name = "enterprise"

        # Guard for missing current_period_end
        cpe_ts = getattr(sub, "current_period_end", None)
        cpe = (
            datetime.fromtimestamp(cpe_ts, tz=timezone.utc)
            if isinstance(cpe_ts, int)
            else None
        )

        logger.info(
            "Found subscription for %s: id=%s status=%s plan=%s cpe=%s",
            email,
            getattr(sub, "id", None),
            raw_status,
            plan_name,
            cpe,
        )

        return SubscriptionStatusResponse(
            email=email,
            status=raw_status,
            plan=plan_name,
            current_period_end=cpe,
        )

    except stripe.error.StripeError:
        logger.exception("Error looking up subscription status")
        return SubscriptionStatusResponse(email=email, status="error")
