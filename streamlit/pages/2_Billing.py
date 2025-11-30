# server/webhook.py

import os
import logging
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import stripe

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-report-backend")

# -------------------------------------------------------------------
# Stripe & env configuration
# -------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY not set in environment.")

stripe.api_key = STRIPE_SECRET_KEY

# Price IDs for each plan (set these in Render's Environment tab)
PRICE_BASIC_ID = os.getenv("PRICE_BASIC")
PRICE_PRO_ID = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE_ID = os.getenv("PRICE_ENTERPRISE")

if not all([PRICE_BASIC_ID, PRICE_PRO_ID, PRICE_ENTERPRISE_ID]):
    raise RuntimeError(
        "One or more Stripe price IDs are missing. "
        "Please set PRICE_BASIC, PRICE_PRO, and PRICE_ENTERPRISE in the environment."
    )

PLAN_TO_PRICE: Dict[str, str] = {
    "basic": PRICE_BASIC_ID,
    "pro": PRICE_PRO_ID,
    "enterprise": PRICE_ENTERPRISE_ID,
}
PRICE_TO_PLAN: Dict[str, str] = {v: k for k, v in PLAN_TO_PRICE.items()}

# Frontend Billing URL used in success/cancel URLs
FRONTEND_BILLING_URL = os.getenv(
    "FRONTEND_BILLING_URL", "https://ai-report-saas.onrender.com/Billing"
).rstrip("/")


# -------------------------------------------------------------------
# FastAPI app setup
# -------------------------------------------------------------------

app = FastAPI(title="AI Report Backend")

# CORS: allow your frontend domain(s)
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://ai-report-saas.onrender.com")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://localhost:8501", "http://localhost:8502"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan: str  # "basic" | "pro" | "enterprise"
    email: EmailStr


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusRequest(BaseModel):
    email: EmailStr


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    plan: str  # "free" | "basic" | "pro" | "enterprise" | "unknown"
    stripe_customer_id: Optional[str] = None
    subscription_id: Optional[str] = None


# -------------------------------------------------------------------
# Health check
# -------------------------------------------------------------------

@app.get("/health")
async def health():
    """
    Simple health-check endpoint for Render.
    """
    return {"status": "ok"}


# -------------------------------------------------------------------
# Create Stripe Checkout session
# -------------------------------------------------------------------

@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(payload: CheckoutRequest):
    """
    Create a Stripe Checkout session for a subscription plan.

    Receives:
        {
            "plan": "basic" | "pro" | "enterprise",
            "email": "user@example.com"
        }

    Returns:
        {
            "checkout_url": "https://checkout.stripe.com/..."
        }
    """
    plan = payload.plan.lower()
    email = payload.email

    if plan not in PLAN_TO_PRICE:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {plan}")

    price_id = PLAN_TO_PRICE[plan]

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=email,
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            success_url=f"{FRONTEND_BILLING_URL}?status=success"
                        f"&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_BILLING_URL}?status=cancel",
            # This is important: we let Stripe create the customer automatically
            # in subscription mode, which is allowed.
        )
    except Exception as exc:
        logger.exception("Error creating Stripe checkout session")
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info(
        "Created checkout session for %s plan. email=%s, session_id=%s",
        plan,
        email,
        session.id,
    )

    return CheckoutResponse(checkout_url=session.url)


# -------------------------------------------------------------------
# Subscription status lookup
# -------------------------------------------------------------------

@app.post("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(payload: SubscriptionStatusRequest):
    """
    Check what plan (if any) the given email is subscribed to.

    Logic:
    - Find Stripe customer by email.
    - List that customer's subscriptions.
    - If there's an active or trialing subscription, map its price_id
      back to "basic" | "pro" | "enterprise".
    - Otherwise return "free".
    """
    email = payload.email

    try:
        customers = stripe.Customer.list(email=email, limit=1)
    except Exception as exc:
        logger.exception("Error listing customers in Stripe")
        raise HTTPException(status_code=500, detail=str(exc))

    if not customers.data:
        # No Stripe customer yet => definitely free
        logger.info("No Stripe customer found for email %s", email)
        return SubscriptionStatusResponse(email=email, plan="free")

    customer = customers.data[0]
    customer_id = customer.id

    try:
        subs = stripe.Subscription.list(customer=customer_id, status="all", limit=5)
    except Exception as exc:
        logger.exception("Error listing subscriptions in Stripe")
        raise HTTPException(status_code=500, detail=str(exc))

    active_sub = None
    for sub in subs.data:
        if sub.status in ("active", "trialing"):
            active_sub = sub
            break

    if not active_sub:
        logger.info("No active/trialing subscription for customer %s", customer_id)
        return SubscriptionStatusResponse(
            email=email,
            plan="free",
            stripe_customer_id=customer_id,
        )

    # Determine plan from first line item's price
    try:
        items = active_sub["items"]["data"]
        if not items:
            raise ValueError("Subscription has no items.")
        price_id = items[0]["price"]["id"]
    except Exception as exc:
        logger.exception("Error extracting price from subscription %s", active_sub.id)
        # We have a subscription but can't map it to a plan
        return SubscriptionStatusResponse(
            email=email,
            plan="unknown",
            stripe_customer_id=customer_id,
            subscription_id=active_sub.id,
        )

    plan = PRICE_TO_PLAN.get(price_id, "unknown")

    logger.info(
        "Found subscription for email %s: plan=%s, sub_id=%s, price_id=%s",
        email,
        plan,
        active_sub.id,
        price_id,
    )

    return SubscriptionStatusResponse(
        email=email,
        plan=plan,
        stripe_customer_id=customer_id,
        subscription_id=active_sub.id,
    )


# -------------------------------------------------------------------
# (Optional) Stripe webhook endpoint - not required for the current flow
# -------------------------------------------------------------------
# If you want to handle async events from Stripe (e.g., subscription
# cancellations), you can fill this out and configure STRIPE_WEBHOOK_SECRET.

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """
    Optional: Stripe webhook endpoint.

    Right now this just verifies the signature (if STRIPE_WEBHOOK_SECRET is set)
    and logs the event type. You can extend this to update your own DB, etc.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    event = None

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=STRIPE_WEBHOOK_SECRET,
            )
        except Exception as exc:
            logger.warning("Invalid Stripe webhook signature: %s", exc)
            raise HTTPException(status_code=400, detail="Invalid webhook signature")
    else:
        # No verification – for dev/testing only
        try:
            event = stripe.Event.construct_from(
                stripe.api_requestor._parse_response(payload.decode("utf-8")),
                stripe.api_key,
            )
        except Exception as exc:
            logger.warning("Could not parse Stripe event: %s", exc)
            raise HTTPException(status_code=400, detail="Invalid payload")

    logger.info("Received Stripe event type=%s", event["type"])

    # You can branch on event["type"] here if needed.
    return {"received": True}
