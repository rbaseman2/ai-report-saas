import os
import json
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import stripe

# ------------------------------------------------------------
# Setup Logging
# ------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-report-backend")

# ------------------------------------------------------------
# Stripe Setup
# ------------------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")

PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

stripe.api_key = STRIPE_SECRET_KEY

# ------------------------------------------------------------
# FastAPI App + CORS
# ------------------------------------------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],         # Streamlit frontend calls this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------
# Helper: Free Plan Response
# ------------------------------------------------------------
def free_plan(email: str):
    return {
        "email": email,
        "plan": "free",
        "max_documents_per_month": 3,
        "source": "fallback"
    }

# Map price → plan name
PRICE_ID_TO_PLAN = {
    PRICE_BASIC:      {"plan": "basic",      "max_documents_per_month": 5},
    PRICE_PRO:        {"plan": "pro",        "max_documents_per_month": 30},
    PRICE_ENTERPRISE: {"plan": "enterprise", "max_documents_per_month": 9999},
}

# ------------------------------------------------------------
# Endpoint: Create a Checkout Session
# ------------------------------------------------------------
@app.post("/create-checkout-session")
async def create_checkout_session(data: dict):
    """
    Input:
    {
        "plan": "basic" | "pro" | "enterprise",
        "email": "rbaseman2@yahoo.com",
        "coupon": "OPTIONAL"
    }
    """
    logger.info("Received checkout request: %s", data)

    plan = data.get("plan")
    email = data.get("email")
    coupon = data.get("coupon")

    if not plan or not email:
        raise HTTPException(status_code=400, detail="Missing plan or email")

    # Select the correct Stripe price ID
    if plan == "basic":
        price_id = PRICE_BASIC
    elif plan == "pro":
        price_id = PRICE_PRO
    elif plan == "enterprise":
        price_id = PRICE_ENTERPRISE
    else:
        raise HTTPException(status_code=400, detail="Invalid plan")

    logger.info("Using Stripe price ID: %s", price_id)

    try:
        params = {
            "mode": "subscription",
            "customer_email": email,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": os.getenv("FRONTEND_URL") + "/Billing?status=success",
            "cancel_url": os.getenv("FRONTEND_URL") + "/Billing?status=cancel",
        }

        # Optional coupon
        if coupon:
            params["discounts"] = [{"coupon": coupon.strip()}]

        session = stripe.checkout.Session.create(**params)
        return {"checkout_url": session.url}

    except stripe.error.StripeError as e:
        logger.error("Stripe error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------
# Stripe Webhook
# ------------------------------------------------------------
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except Exception as e:
        logger.error("Webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Only logging for now
    logger.info("Stripe Webhook event received: %s", event["type"])

    return {"status": "success"}


# ------------------------------------------------------------
# NEW: Subscription Status Endpoint
# ------------------------------------------------------------
@app.get("/subscription-status")
def subscription_status(email: str = Query(..., description="Email to check")):
    """
    Streamlit calls this when user enters email on Upload Data page.
    """

    logger.info("Checking subscription for email %s", email)

    # If Stripe is not configured, default to free plan
    if not STRIPE_SECRET_KEY:
        logger.warning("Stripe key missing! Returning free plan.")
        return free_plan(email)

    try:
        # 1) Find Stripe customer by email
        customers = stripe.Customer.search(
            query=f"email:'{email}'",
            limit=1
        )

        if not customers.data:
            logger.info("No Stripe customer for %s → free plan", email)
            return free_plan(email)

        customer_id = customers.data[0].id

        # 2) Check for active subscription
        subs = stripe.Subscription.list(
            customer=customer_id,
            status="active",
            expand=["data.items.price"],
            limit=1
        )

        if not subs.data:
            logger.info("Customer %s has no active subscription → free plan", email)
            return free_plan(email)

        # Extract price ID
        price_id = subs.data[0].items.data[0].price.id

        logger.info("Customer %s active with price id %s", email, price_id)

        plan_info = PRICE_ID_TO_PLAN.get(price_id)
        if not plan_info:
            logger.warning("Unknown Stripe price id %s → free fallback", price_id)
            return free_plan(email)

        # SUCCESS → return paid plan
        return {
            "email": email,
            "plan": plan_info["plan"],
            "max_documents_per_month": plan_info["max_documents_per_month"],
            "source": "stripe"
        }

    except Exception as e:
        logger.error("Subscription check error: %s", e)
        raise HTTPException(status_code=500, detail="Error checking subscription")


# ------------------------------------------------------------
# Health Check
# ------------------------------------------------------------
@app.get("/")
def health():
    return {"status": "ok", "message": "Backend running"}
