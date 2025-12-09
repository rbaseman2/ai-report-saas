import logging
import os
from typing import Optional

import stripe
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ----- Stripe configuration -----
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY environment variable is required")

stripe.api_key = STRIPE_SECRET_KEY

SUCCESS_URL = os.getenv(
    "SUCCESS_URL",
    "https://ai-report-saas.onrender.com/Billing",
)
CANCEL_URL = os.getenv(
    "CANCEL_URL",
    "https://ai-report-saas.onrender.com/Billing",
)

# ----- FastAPI app -----
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CheckoutRequest(BaseModel):
    email: str
    plan: str  # "basic" | "pro" | "enterprise"


class SubscriptionStatusResponse(BaseModel):
    status: str
    current_period_end: Optional[int] = None
    plan: Optional[str] = None


def price_for_plan(plan: str) -> str:
    """
    Map logical plan names from the UI to Stripe price IDs.
    Raises HTTPException(400) if the plan is invalid or not configured.
    """
    plan = (plan or "").strip().lower()
    if not plan:
        raise HTTPException(status_code=400, detail="Plan is required.")

    try:
        if plan == "basic":
            return os.environ["STRIPE_BASIC_PRICE_ID"]
        elif plan == "pro":
            return os.environ["STRIPE_PRO_PRICE_ID"]
        elif plan == "enterprise":
            return os.environ["STRIPE_ENTERPRISE_PRICE_ID"]
        else:
            raise KeyError(plan)
    except KeyError:
        # Either unknown plan key, or missing env var
        raise HTTPException(status_code=400, detail="Invalid plan requested.")


# ----- Health check -----
@app.get("/health")
async def health():
    return {"status": "ok"}


# ----- Create checkout session -----
@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutRequest):
    """
    Called from the Billing Streamlit page.
    Expects JSON: { "email": "...", "plan": "basic|pro|enterprise" }
    Returns: { "checkout_url": "https://checkout.stripe.com/..." }
    """
    price_id = price_for_plan(data.plan)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=data.email,
            success_url=SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=CANCEL_URL,
            # This makes the "Have a promo code?" field appear on the
            # Stripe checkout page. You configure coupons directly in Stripe.
            allow_promotion_codes=True,
        )
    except stripe.error.StripeError as e:
        logging.exception("Stripe error during checkout")
        msg = getattr(e, "user_message", None) or str(e)
        raise HTTPException(status_code=400, detail=msg)

    return {"checkout_url": session.url}


# ----- Subscription status (optional, used by Billing page) -----
@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: str):
    """
    Check if the given email has an active Stripe subscription.
    """
    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return SubscriptionStatusResponse(status="none")

        customer = customers.data[0]
        subs = stripe.Subscription.list(
            customer=customer.id,
            limit=1,
            status="all",
        )
        if not subs.data:
            return SubscriptionStatusResponse(status="none")

        sub = subs.data[0]
        items = sub["items"]["data"]
        plan_nickname = None
        if items:
            plan_nickname = items[0]["price"].get("nickname")

        return SubscriptionStatusResponse(
            status=sub.status,
            current_period_end=sub.current_period_end,
            plan=plan_nickname,
        )
    except stripe.error.StripeError as e:
        logging.exception("Stripe error while checking subscription status")
        msg = getattr(e, "user_message", None) or str(e)
        raise HTTPException(status_code=400, detail=msg)


# ----- Stripe webhook (for future expansion) -----
@app.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
):
    """
    Generic Stripe webhook handler. Right now it just verifies the signature
    and logs the event type so it always returns 200.
    """
    payload = await request.body()
    endpoint_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    if not endpoint_secret:
        # If you haven't configured a webhook secret yet,
        # don't fail – just accept the event.
        logging.warning("STRIPE_WEBHOOK_SECRET not configured; skipping verification.")
        return {"received": True}

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=endpoint_secret,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    logging.info("Received Stripe event type: %s", event["type"])
    # You can add per-event handling here later (invoice.paid, etc.)

    return {"received": True}
