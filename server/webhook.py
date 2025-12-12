import os
import json
import logging
from typing import Optional, Literal, Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

import stripe

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-report-backend")

# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI(title="AI Report Backend", version="1.0.0")

# ----------------------------
# Env / Config
# ----------------------------
def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    return val if val and str(val).strip() else default

FRONTEND_URL = _get_env("FRONTEND_URL", "http://localhost:8501")
SUCCESS_URL = _get_env("SUCCESS_URL", f"{FRONTEND_URL}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}")
CANCEL_URL = _get_env("CANCEL_URL", f"{FRONTEND_URL}/Billing?status=cancel")

# Stripe keys (you have both in screenshots; we support both names)
STRIPE_SECRET_KEY = _get_env("STRIPE_SECRET_KEY") or _get_env("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = _get_env("STRIPE_WEBHOOK_SECRET")

STRIPE_PRICE_BASIC = _get_env("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = _get_env("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = _get_env("STRIPE_PRICE_ENTERPRISE")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def stripe_is_configured() -> bool:
    # Require at least secret key + all price ids for billing flows
    if not STRIPE_SECRET_KEY:
        return False
    if not (STRIPE_PRICE_BASIC and STRIPE_PRICE_PRO and STRIPE_PRICE_ENTERPRISE):
        return False
    return True


# ----------------------------
# Models
# ----------------------------
PlanName = Literal["basic", "pro", "enterprise"]

class CreateCheckoutSessionRequest(BaseModel):
    email: EmailStr
    plan: PlanName


class CreateCheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    status: str              # "active", "trialing", "canceled", "none", etc.
    plan: Optional[str]      # "basic"/"pro"/"enterprise"/"unknown"/None
    price_id: Optional[str]  # helpful for debugging


# ----------------------------
# Helpers
# ----------------------------
def plan_to_price_id(plan: PlanName) -> str:
    if plan == "basic":
        if not STRIPE_PRICE_BASIC:
            raise HTTPException(status_code=500, detail="STRIPE_PRICE_BASIC is not set")
        return STRIPE_PRICE_BASIC
    if plan == "pro":
        if not STRIPE_PRICE_PRO:
            raise HTTPException(status_code=500, detail="STRIPE_PRICE_PRO is not set")
        return STRIPE_PRICE_PRO
    if plan == "enterprise":
        if not STRIPE_PRICE_ENTERPRISE:
            raise HTTPException(status_code=500, detail="STRIPE_PRICE_ENTERPRISE is not set")
        return STRIPE_PRICE_ENTERPRISE
    raise HTTPException(status_code=400, detail="Invalid plan")


def map_price_to_plan(price_id: Optional[str]) -> Optional[str]:
    """
    Returns plan name if price_id matches env price IDs.
    If subscription exists but doesn't match, return "unknown" (debuggable).
    If no price_id, return None.
    """
    if not price_id:
        return None

    if STRIPE_PRICE_BASIC and price_id == STRIPE_PRICE_BASIC:
        return "basic"
    if STRIPE_PRICE_PRO and price_id == STRIPE_PRICE_PRO:
        return "pro"
    if STRIPE_PRICE_ENTERPRISE and price_id == STRIPE_PRICE_ENTERPRISE:
        return "enterprise"

    return "unknown"


def get_or_create_customer_by_email(email: str) -> stripe.Customer:
    # Search customer by email
    customers = stripe.Customer.list(email=email, limit=1)
    if customers.data:
        return customers.data[0]
    # Create if not found
    return stripe.Customer.create(email=email)


def find_active_or_trialing_subscription(customer_id: str) -> Optional[Dict[str, Any]]:
    # Pull recent subs; expand price so we can map plan cleanly
    subs = stripe.Subscription.list(
        customer=customer_id,
        status="all",
        limit=20,
        expand=["data.items.data.price"]
    )

    for s in subs.data:
        if s.status in ("active", "trialing"):
            return s
    return None


# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/create-checkout-session", response_model=CreateCheckoutSessionResponse)
def create_checkout_session(payload: CreateCheckoutSessionRequest):
    if not stripe_is_configured():
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    price_id = plan_to_price_id(payload.plan)
    customer = get_or_create_customer_by_email(payload.email)

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer.id,
        line_items=[{"price": price_id, "quantity": 1}],
        # ✅ This restores the coupon/promo code box
        allow_promotion_codes=True,
        success_url=SUCCESS_URL,
        cancel_url=CANCEL_URL,
        metadata={
            "plan": payload.plan,
            "email": payload.email,
        },
    )

    logger.info(f"Created checkout session {session.id} for plan={payload.plan} email={payload.email}")
    return CreateCheckoutSessionResponse(checkout_url=session.url, session_id=session.id)


@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
def subscription_status(email: EmailStr):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    # Find customer
    customers = stripe.Customer.list(email=str(email), limit=1)
    if not customers.data:
        return SubscriptionStatusResponse(
            email=email,
            status="none",
            plan=None,
            price_id=None
        )

    customer = customers.data[0]
    sub = find_active_or_trialing_subscription(customer.id)

    if not sub:
        return SubscriptionStatusResponse(
            email=email,
            status="none",
            plan=None,
            price_id=None
        )

    # Get first subscription item price id
    price_id = None
    try:
        if sub["items"]["data"]:
            price_id = sub["items"]["data"][0]["price"]["id"]
    except Exception:
        price_id = None

    plan = map_price_to_plan(price_id)

    logger.info(f"subscription-status email={email} status={sub.status} plan={plan} price_id={price_id}")
    return SubscriptionStatusResponse(
        email=email,
        status=sub.status,
        plan=plan,
        price_id=price_id
    )


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    # If you haven't configured webhook verification yet, we'll still accept events safely,
    # but verification is strongly recommended in production.
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    event = None

    if STRIPE_WEBHOOK_SECRET and sig_header:
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=STRIPE_WEBHOOK_SECRET,
            )
        except Exception as e:
            logger.exception("Webhook signature verification failed")
            raise HTTPException(status_code=400, detail=f"Invalid signature: {str(e)}")
    else:
        # Fallback: parse without verification (not ideal)
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid payload")

    # Stripe SDK event object vs dict fallback:
    event_type = event["type"] if isinstance(event, dict) else event.type

    try:
        if event_type == "checkout.session.completed":
            session_obj = event["data"]["object"] if isinstance(event, dict) else event.data.object
            logger.info(f"checkout.session.completed session_id={session_obj.get('id') if isinstance(session_obj, dict) else session_obj.id}")

        elif event_type in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            sub_obj = event["data"]["object"] if isinstance(event, dict) else event.data.object
            sub_id = sub_obj.get("id") if isinstance(sub_obj, dict) else sub_obj.id
            logger.info(f"{event_type} subscription_id={sub_id}")

        else:
            logger.info(f"Unhandled event type: {event_type}")

    except Exception:
        logger.exception("Error processing webhook event")
        # Don't fail webhook for non-critical processing errors unless you want Stripe retries
        return JSONResponse({"received": True, "processed": False}, status_code=200)

    return {"received": True}
