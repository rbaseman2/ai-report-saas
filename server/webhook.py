# server/webhook.py

import os
import logging
from typing import Optional, Dict, Any, List

import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import JSONResponse, Response

# -------------------------------------------------------------------
# Logging setup
# -------------------------------------------------------------------
logger = logging.getLogger("ai-report-backend")
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------------------------
# Stripe configuration
# -------------------------------------------------------------------
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

STRIPE_PRICE_BASIC = os.environ.get("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_ENTERPRISE = os.environ.get("STRIPE_PRICE_ENTERPRISE", "")

# Optional: name of a promotion code like "welcome"
STRIPE_COUPON_CODE = os.environ.get("STRIPE_COUPON_CODE", "")

# Base URL of your Streamlit frontend, e.g. "https://ai-report-saas.onrender.com"
FRONTEND_BASE_URL = os.environ.get(
    "FRONTEND_BASE_URL", "https://ai-report-saas.onrender.com"
)

if STRIPE_API_KEY:
    stripe.api_key = STRIPE_API_KEY
else:
    logger.warning("STRIPE_API_KEY is not set – Stripe calls will fail.")

# Map plan names used by the frontend to Stripe price IDs
PLAN_TO_PRICE: Dict[str, str] = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

# Reverse lookup from price_id -> plan_name
PRICE_TO_PLAN: Dict[str, str] = {v: k for k, v in PLAN_TO_PRICE.items() if v}

# -------------------------------------------------------------------
# FastAPI app & CORS
# -------------------------------------------------------------------
app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can restrict this to your domains if you like
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------
class CheckoutRequest(BaseModel):
    email: str
    plan: str  # "basic" | "pro" | "enterprise"
    coupon: Optional[str] = None  # e.g. "welcome"


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    has_active_subscription: bool
    status: Optional[str] = None
    plan_name: Optional[str] = None
    current_period_end: Optional[int] = None  # Unix timestamp
    raw_subscription_status: Optional[str] = None


class SummarizeRequest(BaseModel):
    text: str
    recipient_email: Optional[str] = None
    send_email: bool = False


# -------------------------------------------------------------------
# Health check
# -------------------------------------------------------------------
@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# -------------------------------------------------------------------
# Helper functions for Stripe
# -------------------------------------------------------------------
def _find_customer_by_email(email: str) -> Optional[str]:
    """Return Stripe customer ID for a given email, or None."""
    customers = stripe.Customer.list(email=email, limit=1)
    if customers.data:
        return customers.data[0].id
    return None


def _get_latest_active_subscription(customer_id: str):
    """
    Return the most recent non-canceled subscription for the given customer,
    or None if none found.
    """
    subs = stripe.Subscription.list(
        customer=customer_id,
        status="all",
        limit=10,
    )

    if not subs.data:
        return None

    # Filter out obviously inactive ones
    candidates: List[Any] = [
        s
        for s in subs.data
        if s.get("status")
        not in ("canceled", "unpaid", "incomplete_expired")
    ]

    if not candidates:
        return None

    # Pick the one with the latest 'created' timestamp
    latest = max(candidates, key=lambda s: s.get("created", 0))
    return latest


def _lookup_promotion_code(code: str) -> Optional[str]:
    """
    Given a human-entered coupon code (like "welcome"), return
    the Stripe promotion_code ID to use in discounts, or None
    if not found.
    """
    if not code:
        return None

    try:
        promo_list = stripe.PromotionCode.list(code=code, active=True, limit=1)
        if promo_list.data:
            promo_id = promo_list.data[0].id
            logger.info("Resolved coupon %s to promotion_code %s", code, promo_id)
            return promo_id
    except Exception as e:
        logger.error("Error looking up promotion code %s: %s", code, e)

    return None


# -------------------------------------------------------------------
# Create Checkout Session
# -------------------------------------------------------------------
@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(payload: CheckoutRequest):
    logger.info(
        "Creating checkout session for email=%s plan=%s coupon=%s",
        payload.email,
        payload.plan,
        payload.coupon,
    )

    price_id = PLAN_TO_PRICE.get(payload.plan)
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown plan '{payload.plan}'. Expected one of: {list(PLAN_TO_PRICE.keys())}",
        )

    # Build common kwargs
    kwargs: Dict[str, Any] = {
        "mode": "subscription",
        "customer_email": payload.email,
        "line_items": [
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        "success_url": f"{FRONTEND_BASE_URL}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{FRONTEND_BASE_URL}/Billing?status=cancelled",
    }

    # Coupon logic:
    # - If we successfully resolve the coupon to a promotion_code ID,
    #   pass it via `discounts=[{"promotion_code": ...}]`
    # - If no coupon, allow user to enter any promo at checkout with `allow_promotion_codes=True`
    promotion_id = _lookup_promotion_code(payload.coupon) if payload.coupon else None

    if promotion_id:
        kwargs["discounts"] = [{"promotion_code": promotion_id}]
        # Stripe requirement: when `discounts` is used, DO NOT also set allow_promotion_codes
    else:
        # No explicit discount; let Stripe Checkout accept promo codes at the UI level
        kwargs["allow_promotion_codes"] = True

    try:
        session = stripe.checkout.Session.create(**kwargs)
    except stripe.error.StripeError as e:
        logger.error("Stripe error creating checkout session: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Unexpected error creating checkout session: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")

    logger.info(
        "Created checkout session %s for plan %s and email %s",
        session.id,
        payload.plan,
        payload.email,
    )

    return CheckoutResponse(checkout_url=session.url)


# -------------------------------------------------------------------
# Stripe Webhook
# -------------------------------------------------------------------
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        logger.warning(
            "STRIPE_WEBHOOK_SECRET is not set; rejecting webhook for safety."
        )
        return Response(status_code=400)

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        # Invalid payload
        return Response(status_code=400)
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        return Response(status_code=400)

    event_type = event.get("type")
    logger.info("Received Stripe webhook event: %s", event_type)

    # You can add custom handling here if needed
    # For now we just acknowledge
    return Response(status_code=200)


# -------------------------------------------------------------------
# Subscription status endpoint
# -------------------------------------------------------------------
@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: str):
    """
    Returns whether an email has an active Stripe subscription, and if so,
    which plan it corresponds to.
    """
    logger.info("Checking subscription status for email=%s", email)

    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    try:
        customer_id = _find_customer_by_email(email)
        if not customer_id:
            logger.info("No Stripe customer found for email=%s", email)
            return SubscriptionStatusResponse(
                has_active_subscription=False,
                status="none",
            )

        sub = _get_latest_active_subscription(customer_id)
        if not sub:
            logger.info(
                "Customer %s (email=%s) has no active subscriptions", customer_id, email
            )
            return SubscriptionStatusResponse(
                has_active_subscription=False,
                status="none",
            )

        raw_status = sub.get("status")
        is_active = raw_status in ("active", "trialing", "past_due")
        current_period_end = sub.get("current_period_end")

        # Determine plan/price ID
        price_id = None
        try:
            # Modern subscriptions usually have items -> data[0] -> price -> id
            items = sub.get("items", {}).get("data") or []
            if items:
                price_obj = items[0].get("price") or {}
                price_id = price_obj.get("id")
            else:
                # Legacy subscriptions might have sub["plan"]["id"]
                plan_obj = sub.get("plan") or {}
                price_id = plan_obj.get("id")
        except Exception as e:
            logger.error("Error extracting price from subscription %s: %s", sub.id, e)

        plan_name = PRICE_TO_PLAN.get(price_id)

        logger.info(
            "Subscription status for %s: is_active=%s raw_status=%s plan_name=%s price_id=%s",
            email,
            is_active,
            raw_status,
            plan_name,
            price_id,
        )

        if not is_active:
            return SubscriptionStatusResponse(
                has_active_subscription=False,
                status="none",
                raw_subscription_status=raw_status,
            )

        return SubscriptionStatusResponse(
            has_active_subscription=True,
            status="active",
            plan_name=plan_name,
            current_period_end=current_period_end,
            raw_subscription_status=raw_status,
        )

    except Exception as e:
        logger.error("Error looking up subscription status: %s", e)
        # We still respond 200 so the frontend can show a generic message
        return SubscriptionStatusResponse(
            has_active_subscription=False,
            status="none",
        )


# -------------------------------------------------------------------
# Summarize endpoint (for Upload Data page)
# NOTE: This is a minimal implementation so the route exists and returns
# something useful. You can replace the body with your real LLM + email logic.
# -------------------------------------------------------------------
@app.post("/summarize")
async def summarize(request: Request):
    """
    Accepts JSON with at least a 'text' field and optionally
    'recipient_email' and 'send_email'.

    Example payload:
    {
        "text": "raw text to summarize",
        "recipient_email": "user@example.com",
        "send_email": true
    }
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Expected JSON body")

    text = data.get("text")
    recipient_email = data.get("recipient_email")
    send_email = bool(data.get("send_email", False))

    if not text:
        raise HTTPException(status_code=400, detail="Field 'text' is required")

    # Dummy "summary" – in your real backend, call OpenAI or another LLM here
    summary = f"Summary (first 500 chars): {text[:500]}"

    # You can hook in email sending here if send_email is True
    if send_email and recipient_email:
        logger.info(
            "Would send summary email to %s (email sending not implemented in this stub).",
            recipient_email,
        )

    return JSONResponse(
        {
            "summary": summary,
            "recipient_email": recipient_email,
            "email_sent": bool(send_email and recipient_email),
        }
    )
