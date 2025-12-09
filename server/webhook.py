import os
import logging
from typing import Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import stripe

logger = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO)

# ---------- Stripe / environment config ----------

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY env var is required")

stripe.api_key = STRIPE_SECRET_KEY

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://ai-report-saas.onrender.com")
SUCCESS_URL = f"{FRONTEND_URL}/Billing"
CANCEL_URL = f"{FRONTEND_URL}/Billing"

PRICE_IDS: Dict[str, str] = {
    "basic": os.environ.get("STRIPE_BASIC_PRICE_ID", ""),
    "pro": os.environ.get("STRIPE_PRO_PRICE_ID", ""),
    "enterprise": os.environ.get("STRIPE_ENTERPRISE_PRICE_ID", ""),
}

# Make sure we at least have *some* price IDs configured
if not any(PRICE_IDS.values()):
    logger.warning("No Stripe price IDs configured in environment variables")

WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

# ---------- FastAPI app ----------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can tighten this later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CheckoutSessionRequest(BaseModel):
    plan: str  # "basic" | "pro" | "enterprise"
    email: EmailStr


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutSessionRequest) -> dict:
    plan_key = data.plan.lower()
    price_id = PRICE_IDS.get(plan_key)

    if not price_id:
        raise HTTPException(status_code=422, detail="Invalid plan selected")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=data.email,
            line_items=[{"price": price_id, "quantity": 1}],
            # This is what makes the coupon/promo box appear on Stripe Checkout
            allow_promotion_codes=True,
            success_url=f"{SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=CANCEL_URL,
            metadata={"plan": plan_key, "email": data.email},
        )
    except stripe.error.StripeError as exc:
        logger.exception("Stripe error while creating checkout session")
        raise HTTPException(status_code=500, detail=str(exc))

    return {"checkout_url": session.url}


@app.get("/subscription-status")
async def subscription_status(email: str) -> dict:
    """
    Given a billing email, return the current subscription status and plan.
    """
    try:
        customers = stripe.Customer.list(email=email, limit=1)
    except stripe.error.StripeError as exc:
        logger.exception("Stripe error while looking up customer")
        raise HTTPException(status_code=500, detail=str(exc))

    if not customers.data:
        return {"active": False, "plan": None, "status": "none"}

    customer = customers.data[0]

    try:
        subs = stripe.Subscription.list(customer=customer.id, status="all", limit=1)
    except stripe.error.StripeError as exc:
        logger.exception("Stripe error while listing subscriptions")
        raise HTTPException(status_code=500, detail=str(exc))

    if not subs.data:
        return {"active": False, "plan": None, "status": "none"}

    sub = subs.data[0]
    status = sub.status
    price_id = sub["items"]["data"][0]["price"]["id"]

    plan_key = None
    for key, pid in PRICE_IDS.items():
        if pid and pid == price_id:
            plan_key = key
            break

    return {
        "active": status in ("trialing", "active", "past_due"),
        "plan": plan_key,
        "status": status,
        "current_period_end": sub.current_period_end,
    }


@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")

    if WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=WEBHOOK_SECRET,
            )
        except ValueError:
            # Invalid payload
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            # Invalid signature
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # If you haven't configured a webhook secret yet, just parse the JSON without verification.
        logger.warning("STRIPE_WEBHOOK_SECRET not set; skipping signature verification")
        # This is a minimal fallback; for production you should configure WEBHOOK_SECRET.
        import json as _json
        event = stripe.Event.construct_from(_json.loads(payload.decode("utf-8")), stripe.api_key)

    logger.info("Received Stripe event: %s", event["type"])

    # Add per-event handling here if you want.
    return {"received": True}
