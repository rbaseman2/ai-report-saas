import os
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import stripe

# ---------------------------------------------------------------------------
# Config & setup
# ---------------------------------------------------------------------------

logger = logging.getLogger("server.webhook")
logging.basicConfig(level=logging.INFO)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")
SUCCESS_URL = os.getenv(
    "SUCCESS_URL",
    f"{FRONTEND_URL}/Billing?status=success",
)
CANCEL_URL = f"{FRONTEND_URL}/Billing?status=cancelled"

PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY is not set – Stripe calls will fail.")
else:
    stripe.api_key = STRIPE_SECRET_KEY

price_map = {
    "basic": PRICE_BASIC,
    "pro": PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        FRONTEND_URL.replace("https://", "http://"),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CheckoutSessionRequest(BaseModel):
    plan: str                # "basic" | "pro" | "enterprise"
    email: EmailStr
    coupon: Optional[str] = None


class SubscriptionStatusResponse(BaseModel):
    status: str              # "free" | "active"
    plan: Optional[str] = None   # "basic" | "pro" | "enterprise" | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutSessionRequest):
    """
    Creates a Stripe Checkout Session and returns the URL.

    IMPORTANT: The frontend expects a JSON response like:
      { "checkout_url": "https://checkout.stripe.com/..." }
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    plan_key = data.plan.lower()
    if plan_key not in price_map or not price_map[plan_key]:
        raise HTTPException(status_code=400, detail="Invalid plan")

    price_id = price_map[plan_key]

    try:
        params = {
            "mode": "subscription",
            "customer_email": data.email,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": SUCCESS_URL,
            "cancel_url": CANCEL_URL,
        }

        if data.coupon:
            params["discounts"] = [{"coupon": data.coupon}]

        session = stripe.checkout.Session.create(**params)
        logger.info(
            "Created checkout session %s for %s (%s)",
            session.id,
            data.email,
            plan_key,
        )

        # 🔴 This field name must match what the frontend expects
        return {"checkout_url": session.url}

    except stripe.error.StripeError as e:
        logger.exception("Stripe error while creating checkout session: %s", e)
        raise HTTPException(status_code=502, detail="Stripe error")
    except Exception as e:
        logger.exception("Unexpected error while creating checkout session: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr):
    """
    Returns the current subscription status for a given email,
    based directly on Stripe data.
    """
    if not STRIPE_SECRET_KEY:
        # If Stripe is not configured, just act like everyone is on free
        return SubscriptionStatusResponse(status="free", plan=None)

    try:
        # 1) Find Stripe customer by email
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return SubscriptionStatusResponse(status="free", plan=None)

        customer = customers.data[0]

        # 2) Look for an active subscription
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="active",
            limit=1,
        )

        if not subs.data:
            return SubscriptionStatusResponse(status="free", plan=None)

        sub = subs.data[0]
        price_id = sub["items"]["data"][0]["price"]["id"]

        # 3) Reverse map price ID -> plan name
        plan = None
        for key, pid in price_map.items():
            if pid == price_id:
                plan = key
                break

        return SubscriptionStatusResponse(status="active", plan=plan)

    except stripe.error.StripeError as e:
        logger.exception("Stripe error checking subscription status: %s", e)
        # Fallback to "free" so the UI still works
        return SubscriptionStatusResponse(status="free", plan=None)
    except Exception as e:
        logger.exception("Unexpected error checking subscription status: %s", e)
        return SubscriptionStatusResponse(status="free", plan=None)


@app.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
):
    """
    Stripe webhook endpoint.

    Make sure STRIPE_WEBHOOK_SECRET in Render matches the signing secret
    from your Stripe dashboard for this endpoint.
    """
    if not WEBHOOK_SECRET:
        logger.warning("Received webhook but STRIPE_WEBHOOK_SECRET is not set")
        raise HTTPException(status_code=500, detail="Webhook not configured")

    payload = await request.body()
    sig_header = stripe_signature

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=WEBHOOK_SECRET,
        )
    except ValueError:
        logger.exception("Invalid payload in Stripe webhook")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        logger.exception("Invalid signature in Stripe webhook")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the events you care about
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        logger.info("Checkout session completed: %s", session.get("id"))
        # TODO: add any post-checkout logic you want here.

    elif event["type"] == "customer.subscription.deleted":
        sub = event["data"]["object"]
        logger.info("Subscription cancelled: %s", sub.get("id"))
        # TODO: update your records if you store subscriptions.

    # Always respond 200 so Stripe knows we received the event
    return {"received": True}
