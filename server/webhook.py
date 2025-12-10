import logging
import os
from typing import Literal, Optional, Dict

import stripe
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, EmailStr, AnyHttpUrl

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI()

# -----------------------------------------------------------------------------
# Stripe configuration
# -----------------------------------------------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

STRIPE_PRICE_BASIC = os.environ.get("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_ENTERPRISE = os.environ.get("STRIPE_PRICE_ENTERPRISE", "")

SUCCESS_URL = os.environ.get("SUCCESS_URL", "https://ai-report-saas.onrender.com/Billing")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logging.warning("STRIPE_SECRET_KEY is not set; billing endpoints will be limited")

# plan name -> Stripe price ID
PLAN_TO_PRICE: Dict[str, str] = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

# reverse mapping: price ID -> plan name
PRICE_TO_PLAN: Dict[str, str] = {v: k for k, v in PLAN_TO_PRICE.items() if v}

# -----------------------------------------------------------------------------
# Subscription limits (used by /subscription-status)
# -----------------------------------------------------------------------------
class SubscriptionLimits(BaseModel):
    max_reports_per_month: int
    max_chars_per_month: int


SUBSCRIPTION_LIMITS: Dict[str, SubscriptionLimits] = {
    "free": SubscriptionLimits(max_reports_per_month=5, max_chars_per_month=200_000),
    "basic": SubscriptionLimits(max_reports_per_month=20, max_chars_per_month=400_000),
    "pro": SubscriptionLimits(max_reports_per_month=75, max_chars_per_month=1_500_000),
    "enterprise": SubscriptionLimits(max_reports_per_month=250, max_chars_per_month=5_000_000),
}


# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------
class CheckoutRequest(BaseModel):
    plan: Literal["basic", "pro", "enterprise"]
    email: EmailStr
    # coupon is currently not used; promotion codes are handled on Stripe checkout page
    coupon: Optional[str] = None


class CheckoutResponse(BaseModel):
    checkout_url: AnyHttpUrl


class SubscriptionStatusResponse(BaseModel):
    plan: str
    status: str
    current_period_end: Optional[int]  # Unix timestamp or None
    limits: SubscriptionLimits


# -----------------------------------------------------------------------------
# Simple health endpoint
# -----------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# -----------------------------------------------------------------------------
# Create Stripe Checkout session
# -----------------------------------------------------------------------------
@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(req: CheckoutRequest) -> CheckoutResponse:
    """
    Create a Stripe Checkout session for the selected plan.
    Promotion codes are enabled directly on the Stripe checkout page.
    """

    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    price_id = PLAN_TO_PRICE.get(req.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {req.plan}")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=req.email,
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            # Let customer enter promotion codes on the checkout page
            allow_promotion_codes=True,
            success_url=f"{SUCCESS_URL}?status=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{SUCCESS_URL}?status=cancel",
        )
    except Exception as e:  # noqa: BLE001
        logging.exception("Error creating checkout session: %s", e)
        raise HTTPException(status_code=500, detail="Error creating checkout session")

    return CheckoutResponse(checkout_url=session.url)  # type: ignore[arg-type]


# -----------------------------------------------------------------------------
# Stripe webhook
# -----------------------------------------------------------------------------
@app.post("/webhook")
async def stripe_webhook(request: Request) -> dict:
    """
    Handle Stripe webhook events. Right now we mainly validate the event and log it.
    Subscription status is derived dynamically in /subscription-status, so we don't
    persist anything here.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        logging.warning("STRIPE_WEBHOOK_SECRET not set; skipping signature verification")
        # In that case, just try to parse the event without verification
        try:
            event = stripe.Event.construct_from(request.json(), stripe.api_key)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            logging.exception("Error parsing Stripe event without verification: %s", e)
            raise HTTPException(status_code=400, detail="Invalid Stripe event")
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=STRIPE_WEBHOOK_SECRET,
            )
        except Exception as e:  # noqa: BLE001
            logging.exception("Error verifying Stripe webhook: %s", e)
            raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    # You can add specific event handling here if needed
    logging.info("Received Stripe event: %s", event["type"])

    return {"received": True}


# -----------------------------------------------------------------------------
# Subscription status lookup by email
# -----------------------------------------------------------------------------
@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr) -> SubscriptionStatusResponse:
    """
    Given a customer email, look up the most recent Stripe subscription and map it
    to one of our plan names. If nothing is found, return the 'free' plan.
    """

    # If Stripe isn't configured, treat everyone as free.
    if not STRIPE_SECRET_KEY:
        limits = SUBSCRIPTION_LIMITS["free"]
        return SubscriptionStatusResponse(
            plan="free",
            status="inactive",
            current_period_end=None,
            limits=limits,
        )

    try:
        # 1) Find customer by email
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            limits = SUBSCRIPTION_LIMITS["free"]
            return SubscriptionStatusResponse(
                plan="free",
                status="inactive",
                current_period_end=None,
                limits=limits,
            )

        customer = customers.data[0]

        # 2) Get most recent subscription for that customer (any status)
        subs = stripe.Subscription.list(customer=customer.id, status="all", limit=1)
        if not subs.data:
            limits = SUBSCRIPTION_LIMITS["free"]
            return SubscriptionStatusResponse(
                plan="free",
                status="inactive",
                current_period_end=None,
                limits=limits,
            )

        sub = subs.data[0]

        # 3) Determine which plan this subscription maps to
        price_id = sub["items"]["data"][0]["price"]["id"]
        plan_name = PRICE_TO_PLAN.get(price_id, "unknown")

        limits = SUBSCRIPTION_LIMITS.get(plan_name, SUBSCRIPTION_LIMITS["free"])

        # Some subscription objects might not have current_period_end (e.g., incomplete)
        current_period_end = sub.get("current_period_end", None)

        return SubscriptionStatusResponse(
            plan=plan_name,
            status=sub.status,
            current_period_end=current_period_end,
            limits=limits,
        )

    except Exception as e:  # noqa: BLE001
        logging.exception("Error looking up subscription status: %s", e)
        limits = SUBSCRIPTION_LIMITS["free"]
        return SubscriptionStatusResponse(
            plan="free",
            status="error",
            current_period_end=None,
            limits=limits,
        )
