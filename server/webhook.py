# server/webhook.py

import os
import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# 👇 Re-use the existing FastAPI app that already has /summarize, /health, etc.
# (this is the app you used to run with `uvicorn server.main:app`)
from server.main import app  # type: ignore

# Stripe configuration
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

STRIPE_PRICE_BASIC = os.environ.get("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = os.environ.get("STRIPE_PRICE_ENTERPRISE")

STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

SUCCESS_URL = os.environ.get(
    "SUCCESS_URL",
    "https://ai-report-saas.onrender.com/Billing?status=success",
)
CANCEL_URL = os.environ.get(
    "CANCEL_URL",
    "https://ai-report-saas.onrender.com/Billing?status=cancelled",
)

PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}


class CheckoutRequest(BaseModel):
    plan: str
    email: str
    coupon: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutRequest):
    """
    Create a Stripe Checkout session for a subscription.
    - plan: "basic" | "pro" | "enterprise"
    - email: customer email
    - coupon: optional Stripe coupon id (e.g. "welcome")
    """

    if data.plan not in PLAN_TO_PRICE or not PLAN_TO_PRICE[data.plan]:
        raise HTTPException(status_code=400, detail="Invalid plan selected")

    price_id = PLAN_TO_PRICE[data.plan]

    session_args = {
        "success_url": f"{SUCCESS_URL}&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": CANCEL_URL,
        "payment_method_types": ["card"],
        "mode": "subscription",
        "customer_email": data.email,
        "line_items": [
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
    }

    # ⚠️ You may only use ONE of: allow_promotion_codes OR discounts
    if data.coupon:
        session_args["discounts"] = [{"coupon": data.coupon}]
    else:
        # Allow generic promo codes if the customer has one
        session_args["allow_promotion_codes"] = True

    try:
        session = stripe.checkout.Session.create(**session_args)
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # front-end uses session.url to redirect
    return {"id": session.id, "url": session.url}


@app.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint. Configure this URL in your Stripe dashboard.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=STRIPE_WEBHOOK_SECRET,
            )
        except ValueError:
            # Invalid payload
            return JSONResponse(status_code=400, content={"detail": "Invalid payload"})
        except stripe.error.SignatureVerificationError:
            # Invalid signature
            return JSONResponse(
                status_code=400, content={"detail": "Invalid signature"}
            )
    else:
        # No webhook secret set; trust the payload (dev only)
        try:
            event = stripe.Event.construct_from(
                request.json(), stripe.api_key  # type: ignore[arg-type]
            )
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid event"})

    # Handle the event types you care about
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        # You can add any post-checkout logic here if needed
        # (e.g. logging, updating your own DB, etc.)

    return {"received": True}


@app.get("/subscription-status")
async def subscription_status(email: str):
    """
    Given a customer email, return whether they have an active subscription
    and which plan it maps to (if any).
    """
    try:
        customers = stripe.Customer.list(email=email, limit=1)
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not customers.data:
        return {
            "has_active_subscription": False,
            "plan": None,
            "status": None,
        }

    customer = customers.data[0]

    try:
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="all",  # we’ll manually filter
            expand=["data.items"],
            limit=10,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    active_sub = None
    for sub in subs.data:
        if sub.status in ("active", "trialing"):
            active_sub = sub
            break

    if not active_sub:
        return {
            "has_active_subscription": False,
            "plan": None,
            "status": None,
        }

    # Get the price id of the first item
    try:
        item = active_sub["items"]["data"][0]
        price_id = item["price"]["id"]
    except Exception:
        price_id = None

    plan_name = None
    if price_id:
        for name, pid in PLAN_TO_PRICE.items():
            if pid == price_id:
                plan_name = name
                break

    return {
        "has_active_subscription": True,
        "plan": plan_name,
        "status": active_sub.status,
    }
