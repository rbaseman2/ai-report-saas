# server/webhook.py
import os
import logging
import stripe
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# -------------------------------------------------
# App & logging
# -------------------------------------------------
app = FastAPI()
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# Stripe configuration
# -------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    logging.warning("STRIPE_SECRET_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY

PRICE_IDS = {
    "basic": os.getenv("STRIPE_PRICE_BASIC"),
    "pro": os.getenv("STRIPE_PRICE_PRO"),
    "enterprise": os.getenv("STRIPE_PRICE_ENTERPRISE"),
}

SUCCESS_URL = os.getenv(
    "SUCCESS_URL",
    "https://ai-report-saas.onrender.com/Upload_Data"
)
CANCEL_URL = os.getenv(
    "CANCEL_URL",
    "https://ai-report-saas.onrender.com/Billing"
)

# -------------------------------------------------
# Models
# -------------------------------------------------
class CheckoutRequest(BaseModel):
    email: str
    plan: str

# -------------------------------------------------
# Health check
# -------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# -------------------------------------------------
# Subscription status
# -------------------------------------------------
@app.get("/subscription-status")
def subscription_status(email: str):
    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return {"status": "none", "plan": None}

        customer = customers.data[0]

        subs = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=1,
            expand=["data.items.data.price"],
        )

        if not subs.data:
            return {"status": "none", "plan": None}

        sub = subs.data[0]
        price_id = sub["items"]["data"][0]["price"]["id"]

        plan = None
        for key, value in PRICE_IDS.items():
            if value == price_id:
                plan = key

        return {
            "status": sub.status,
            "plan": plan,
        }

    except Exception as e:
        logging.exception("Error checking subscription status")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------------------------------
# Create Stripe Checkout Session
# -------------------------------------------------
@app.post("/create-checkout-session")
def create_checkout_session(req: CheckoutRequest):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="STRIPE_SECRET_KEY is not set in environment variables.",
        )

    price_id = PRICE_IDS.get(req.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan")

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
            customer_email=req.email,
            success_url=f"{SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=CANCEL_URL,
            allow_promotion_codes=True,
        )

        logging.info(
            f"Checkout session {session.id} created for {req.email} ({req.plan})"
        )

        return {
            "checkout_url": session.url,
            "url": session.url,          # backward compatibility
            "session_id": session.id,
        }

    except Exception as e:
        logging.exception("Failed to create checkout session")
        raise HTTPException(status_code=500, detail=str(e))
