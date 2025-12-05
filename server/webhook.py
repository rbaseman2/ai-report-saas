import os
import json
import stripe
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# -------------------------------------------------------------------
# FASTAPI APP
# -------------------------------------------------------------------

app = FastAPI()

# Allow Streamlit frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# HEALTH CHECK  (REQUIRED FOR RENDER)
# -------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}

# -------------------------------------------------------------------
# STRIPE CONFIG
# -------------------------------------------------------------------

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

SUCCESS_URL = os.getenv("SUCCESS_URL", "https://ai-report-saas.onrender.com/Billing")
CANCEL_URL = os.getenv("CANCEL_URL", "https://ai-report-saas.onrender.com/Billing")

# -------------------------------------------------------------------
# MODELS
# -------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    email: str
    plan: str        # "basic", "pro", "enterprise"
    coupon: Optional[str] = None


class SummaryRequest(BaseModel):
    email: str
    text: str


# -------------------------------------------------------------------
# PRICING LOOKUP
# -------------------------------------------------------------------

PLAN_MAP = {
    "basic": PRICE_BASIC,
    "pro": PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}

# -------------------------------------------------------------------
# CHECKOUT SESSION CREATION
# -------------------------------------------------------------------

@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutRequest):
    if data.plan not in PLAN_MAP:
        raise HTTPException(status_code=400, detail="Invalid plan")

    price_id = PLAN_MAP[data.plan]

    try:
        params = {
            "customer_email": data.email,
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "subscription",
            "success_url": SUCCESS_URL,
            "cancel_url": CANCEL_URL,
        }

        # Optional coupon support
        if data.coupon:
            params["discounts"] = [{"coupon": data.coupon}]

        session = stripe.checkout.Session.create(**params)

        return {"checkout_url": session.url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------
# SUBSCRIPTION STATUS
# -------------------------------------------------------------------

@app.get("/subscription-status")
async def subscription_status(email: str):
    try:
        customers = stripe.Customer.list(email=email).data

        if not customers:
            return {"active": False, "plan": "free"}

        customer = customers[0]

        subs = stripe.Subscription.list(customer=customer.id, status="active").data

        if not subs:
            return {"active": False, "plan": "free"}

        sub = subs[0]
        plan_lookup = {
            PRICE_BASIC: "basic",
            PRICE_PRO: "pro",
            PRICE_ENTERPRISE: "enterprise",
        }

        plan_id = sub.items.data[0].price.id
        plan_name = plan_lookup.get(plan_id, "free")

        # Set limits per plan
        limits = {
            "basic": {"max_documents": 20, "max_chars": 400000},
            "pro": {"max_documents": 75, "max_chars": 1500000},
            "enterprise": {"max_documents": 250, "max_chars": 5000000},
        }.get(plan_name, {"max_documents": 5, "max_chars": 200000})

        return {
            "active": True,
            "plan": plan_name,
            "max_documents": limits["max_documents"],
            "max_chars": limits["max_chars"],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------
# STRIPE WEBHOOK HANDLER
# -------------------------------------------------------------------

@app.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None)
):
    payload = await request.body()

    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret missing")

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle subscription events
    if event["type"] == "customer.subscription.created":
        print("Subscription created:", event["data"]["object"]["id"])

    elif event["type"] == "customer.subscription.updated":
        print("Subscription updated:", event["data"]["object"]["id"])

    elif event["type"] == "customer.subscription.deleted":
        print("Subscription canceled:", event["data"]["object"]["id"])

    return {"status": "success"}


# -------------------------------------------------------------------
# TEXT SUMMARY ENDPOINT
# -------------------------------------------------------------------

@app.post("/summarize")
async def summarize_text(data: SummaryRequest):
    if not data.email:
        raise HTTPException(status_code=422, detail="Missing email")

    if not data.text:
        raise HTTPException(status_code=422, detail="Missing text to summarize")

    # --- AI SUMMARY (replace with your OpenAI model call) ---
    summary = f"Summary:\n\n{data.text[:500]}\n\n...(trimmed)..."

    return {"summary": summary}
