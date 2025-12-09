import os
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import stripe

# ----- Stripe / environment setup -----

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://ai-report-saas.onrender.com")
SUCCESS_URL = os.environ.get(
    "SUCCESS_URL",
    f"{FRONTEND_URL}/Billing",
)
CANCEL_URL = os.environ.get("CANCEL_URL", f"{FRONTEND_URL}/Billing")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY environment variable is required")

stripe.api_key = STRIPE_SECRET_KEY

PLAN_TO_PRICE = {
    "basic": os.environ.get("STRIPE_PRICE_BASIC"),
    "pro": os.environ.get("STRIPE_PRICE_PRO"),
    "enterprise": os.environ.get("STRIPE_PRICE_ENTERPRISE"),
}

# ----- Pydantic models -----


class CheckoutRequest(BaseModel):
    plan: str          # "basic", "pro", or "enterprise"
    email: EmailStr
    coupon: str | None = None   # optional, but we IGNORE it now to avoid Stripe conflict


# ----- FastAPI app setup -----

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "https://ai-report-saas.onrender.com",
        "http://localhost",
        "http://localhost:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ----- Create checkout session -----


@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutRequest):
    price_id = PLAN_TO_PRICE.get(data.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan selected")

    # IMPORTANT: only allow_promotion_codes, no discounts[]
    session_params: dict = {
        "mode": "subscription",
        "customer_email": data.email,
        "line_items": [{"price": price_id, "quantity": 1}],
        # This shows the "Add promotion code" box on Stripe Checkout
        "allow_promotion_codes": True,
        "success_url": SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": CANCEL_URL,
    }

    # We intentionally DO NOT set "discounts" here to avoid:
    # "You may only specify one of these parameters: allow_promotion_codes, discounts"

    try:
        session = stripe.checkout.Session.create(**session_params)
    except stripe.error.StripeError as e:
        # Surface Stripe error back to the frontend
        raise HTTPException(status_code=400, detail=str(e))

    return {"checkout_url": session.url}


# ----- Subscription status lookup -----


@app.get("/subscription-status")
async def subscription_status(email: str):
    """
    Given a customer email, return whether they have an active subscription
    plus some basic metadata.
    """
    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return {"has_active_subscription": False}

        customer = customers.data[0]

        subs = stripe.Subscription.list(customer=customer.id, status="all", limit=10)

        active_sub = None
        for sub in subs.data:
            if sub.status in ("trialing", "active"):
                active_sub = sub
                break

        if not active_sub:
            return {"has_active_subscription": False}

        # Use .get() to avoid KeyError on current_period_end
        current_period_end = active_sub.get("current_period_end")
        cancel_at_period_end = active_sub.get("cancel_at_period_end", False)

        # Try to pull a readable plan name
        plan_nickname = None
        try:
            plan_nickname = active_sub["items"]["data"][0]["plan"].get("nickname")
        except Exception:
            plan_nickname = None

        return {
            "has_active_subscription": True,
            "status": active_sub.status,
            "current_period_end": current_period_end,
            "cancel_at_period_end": cancel_at_period_end,
            "plan_nickname": plan_nickname,
        }

    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----- Stripe webhook (minimal) -----


@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # Fallback: no signature verification (ok for now)
        event = json.loads(payload.decode("utf-8"))

    # You can add specific handling (subscription created/updated, etc.)
    return {"received": True}
