# server/webhook.py

import os
import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Literal

# ======================
# Env & Stripe setup
# ======================

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# FRONTEND_URL is your Streamlit app base (used mainly for CORS)
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://ai-report-saas.onrender.com")

# SUCCESS_URL is where Stripe should send users back after checkout
SUCCESS_URL = os.environ.get(
    "SUCCESS_URL",
    "https://ai-report-saas.onrender.com/Billing",
)

# These env vars already exist in your backend (per your screenshot)
STRIPE_PRICE_BASIC = os.environ.get("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = os.environ.get("STRIPE_PRICE_ENTERPRISE")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY

# Map plan name -> Stripe price ID
PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

# Reverse: price ID -> plan name
PRICE_TO_PLAN = {v: k for k, v in PLAN_TO_PRICE.items() if v}

# Limits returned to the Streamlit Billing page
PLAN_LIMITS = {
    "basic": {"max_documents": 20, "max_chars": 400_000},
    "pro": {"max_documents": 75, "max_chars": 1_500_000},
    "enterprise": {"max_documents": 250, "max_chars": 5_000_000},
}

# ======================
# FastAPI setup
# ======================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "https://ai-report-saas.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================
# Models
# ======================

class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: Literal["basic", "pro", "enterprise"]


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    plan: str
    max_documents: int
    max_chars: int


# ======================
# Health
# ======================

@app.get("/health")
async def health():
    return {"status": "ok"}


# ======================
# Create Checkout Session
# ======================

@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(data: CheckoutRequest):
    price_id = PLAN_TO_PRICE.get(data.plan)

    if not price_id:
        # This is what shows up as "Invalid plan requested" in Streamlit
        raise HTTPException(status_code=400, detail="Invalid plan requested")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=data.email,
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            # Let users enter a promo code directly on the Stripe checkout page
            allow_promotion_codes=True,
            success_url=f"{SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=SUCCESS_URL,
        )
    except stripe.error.StripeError as e:
        # Surface a friendly error to the front-end
        msg = e.user_message or str(e)
        raise HTTPException(status_code=400, detail=f"Stripe error: {msg}")

    return CheckoutResponse(checkout_url=session.url)


# ======================
# Webhook (from Stripe)
# ======================

@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        else:
            # Unsafe, but useful if you haven't configured the webhook secret yet
            event = stripe.Event.construct_from(
                request.json(), stripe.api_key  # type: ignore[arg-type]
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")

    event_type = event["type"]

    # You can expand this later if you want to store subscription info
    if event_type == "checkout.session.completed":
        # session = event["data"]["object"]
        # e.g. you could log or persist data here
        pass

    return {"status": "success"}


# ======================
# Subscription Status
# ======================

@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr):
    """
    Called by the Streamlit Billing page.

    If a subscription is found, we map its price_id back to
    basic/pro/enterprise and return the plan + limits.

    If NOT found, Streamlit treats 404 as "free plan".
    """

    try:
        customers = stripe.Customer.list(email=email, limit=1)
    except stripe.error.StripeError as e:
        msg = e.user_message or str(e)
        raise HTTPException(status_code=500, detail=f"Stripe error: {msg}")

    if not customers.data:
        # Streamlit interprets 404 as "no active subscription"
        raise HTTPException(status_code=404, detail="No customer for this email")

    customer = customers.data[0]

    try:
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="all",  # any status; we just grab the most recent
            limit=1,
        )
    except stripe.error.StripeError as e:
        msg = e.user_message or str(e)
        raise HTTPException(status_code=500, detail=f"Stripe error: {msg}")

    if not subs.data:
        raise HTTPException(status_code=404, detail="No subscription for this customer")

    sub = subs.data[0]

    # Safely get the first price ID
    try:
        items = sub["items"]["data"]
        price_id = items[0]["price"]["id"]
    except (KeyError, IndexError):
        raise HTTPException(status_code=404, detail="Subscription has no price")

    plan = PRICE_TO_PLAN.get(price_id)
    if not plan or plan not in PLAN_LIMITS:
        # Unknown price → treat as "no recognized plan"
        raise HTTPException(status_code=404, detail="Unknown price for subscription")

    limits = PLAN_LIMITS[plan]

    return SubscriptionStatusResponse(
        plan=plan,
        max_documents=limits["max_documents"],
        max_chars=limits["max_chars"],
    )
