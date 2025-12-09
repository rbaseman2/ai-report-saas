# server/webhook.py

import os
import json
from typing import Optional

import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ----- Stripe + env setup -----

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

FRONTEND_URL = os.environ["FRONTEND_URL"]
SUCCESS_URL = os.getenv("SUCCESS_URL", f"{FRONTEND_URL}/UploadData")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

STRIPE_PRICE_BASIC = os.environ["STRIPE_PRICE_BASIC"]
STRIPE_PRICE_PRO = os.environ["STRIPE_PRICE_PRO"]
STRIPE_PRICE_ENTERPRISE = os.environ["STRIPE_PRICE_ENTERPRISE"]

PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

# ----- FastAPI app -----

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Models -----

class CheckoutSessionRequest(BaseModel):
    plan: str
    email: str
    coupon: Optional[str] = None


class CheckoutSessionResponse(BaseModel):
    # Return BOTH so old + new frontends work
    url: str
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    is_active: bool
    plan: Optional[str] = None
    current_period_end: Optional[int] = None


class WebhookAck(BaseModel):
    received: bool


# ----- Health -----

@app.get("/health")
async def health():
    return {"status": "ok"}


# ----- Create checkout session -----

@app.post("/create-checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout_session(data: CheckoutSessionRequest):
    price_id = PLAN_TO_PRICE.get(data.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan selected")

    session_args = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "customer_email": data.email,
        "success_url": f"{SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{FRONTEND_URL}/Billing?canceled=1",
        "metadata": {
            "plan": data.plan,
            "email": data.email,
        },
    }

    if data.coupon:
        # coupon code from your “welcome” coupon, etc.
        session_args["discounts"] = [{"coupon": data.coupon}]

    session = stripe.checkout.Session.create(**session_args)

    # Return both keys to satisfy whatever the Billing page expects
    return CheckoutSessionResponse(
        url=session.url,
        checkout_url=session.url,
    )


# ----- Subscription status (called from Billing page) -----

@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: str):
    # Find customer by email
    customers = stripe.Customer.list(email=email, limit=1)
    if not customers.data:
        return SubscriptionStatusResponse(is_active=False)

    customer = customers.data[0]

    subs = stripe.Subscription.list(
        customer=customer.id,
        status="active",
        limit=1,
    )

    if not subs.data:
        return SubscriptionStatusResponse(is_active=False)

    sub = subs.data[0]
    item = sub["items"]["data"][0]
    price = item["price"]

    # Prefer nickname; fall back to price id
    plan_name = price.get("nickname") or price.get("id")

    return SubscriptionStatusResponse(
        is_active=True,
        plan=plan_name,
        current_period_end=sub.get("current_period_end"),
    )


# ----- Stripe webhook -----

@app.post("/webhook", response_model=WebhookAck)
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        if WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=WEBHOOK_SECRET,
            )
        else:
            # Unsafe, but useful if webhook secret not configured in dev
            event = stripe.Event.construct_from(
                json.loads(payload.decode("utf-8")), stripe.api_key
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # You can add handling here if you want:
    # if event["type"] == "customer.subscription.updated": ...

    return WebhookAck(received=True)
