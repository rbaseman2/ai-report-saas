import os
import json
from typing import Optional, Dict, Any

import stripe
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Stripe configuration from environment
# ---------------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set in the environment")

stripe.api_key = STRIPE_SECRET_KEY

# Price IDs for each plan (configured in Render env vars)
PRICE_BASIC_ID = os.getenv("PRICE_BASIC")
PRICE_PRO_ID = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE_ID = os.getenv("PRICE_ENTERPRISE")

PRICE_BY_PLAN: Dict[str, Optional[str]] = {
    "basic": PRICE_BASIC_ID,
    "pro": PRICE_PRO_ID,
    "enterprise": PRICE_ENTERPRISE_ID,
}

# Frontend URL used for success & cancel redirect
FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    # Fallback to your Streamlit frontend
    "https://ai-report-saas.onrender.com",
)

# ---------------------------------------------------------------------------
# FastAPI app setup
# ---------------------------------------------------------------------------

app = FastAPI(title="AI Report Backend - Stripe Webhook")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can tighten this later
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    """
    Request body for creating a Stripe Checkout session.

    Example:
    {
        "plan": "basic",
        "email": "user@example.com",
        "coupon": "MYCOUPON"  # optional
    }
    """
    plan: str
    email: str
    coupon: Optional[str] = None


# ---------------------------------------------------------------------------
# Health check (for Render)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Create Checkout Session
# ---------------------------------------------------------------------------

@app.post("/create-checkout-session")
async def create_checkout_session(body: CheckoutRequest) -> Dict[str, Any]:
    """
    Create a Stripe Checkout session for a subscription plan.

    The frontend should POST:
    {
        "plan": "basic" | "pro" | "enterprise",
        "email": "user@example.com",
        "coupon": "OPTIONAL_COUPON_CODE"
    }
    """
    plan_key = body.plan.lower().strip()
    price_id = PRICE_BY_PLAN.get(plan_key)

    if not price_id:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or unconfigured plan '{body.plan}'. "
                   f"Check PRICE_BASIC / PRICE_PRO / PRICE_ENTERPRISE env vars.",
        )

    try:
        checkout_kwargs: Dict[str, Any] = {
            "mode": "subscription",
            "payment_method_types": ["card"],
            "customer_email": body.email,
            "line_items": [
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            "success_url": (
                f"{FRONTEND_URL}/Billing"
                "?status=success&session_id={{CHECKOUT_SESSION_ID}}"
            ),
            "cancel_url": f"{FRONTEND_URL}/Billing?status=cancelled",
            # Let Stripe show promotion-code / coupon field
            "allow_promotion_codes": True,
            "metadata": {
                "plan": plan_key,
                "email": body.email,
            },
        }

        # If you want to force a specific coupon code instead of promo box:
        if body.coupon:
            checkout_kwargs["discounts"] = [{"coupon": body.coupon}]

        session = stripe.checkout.Session.create(**checkout_kwargs)

        print(
            f"[create-checkout-session] email={body.email} plan={plan_key} "
            f"session_id={session.id}"
        )

        return {"checkout_url": session.url}

    except stripe.error.StripeError as e:
        # Surface Stripe error messages to the frontend in a friendly way
        msg = getattr(e, "user_message", str(e))
        print(f"[Stripe error] {msg}")
        raise HTTPException(status_code=500, detail=f"Stripe error: {msg}")
    except Exception as e:
        print(f"[create-checkout-session] unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Error creating checkout session")


# ---------------------------------------------------------------------------
# Stripe Webhook
# ---------------------------------------------------------------------------

@app.post("/webhook")
async def stripe_webhook(request: Request) -> Dict[str, bool]:
    """
    Handle incoming Stripe webhook events.

    This implementation:
      - Verifies the signature (if STRIPE_WEBHOOK_SECRET is set)
      - Logs subscription events
      - Does NOT touch any database (safe Option A).
    """

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    # Verify Stripe signature if a webhook secret is configured
    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=STRIPE_WEBHOOK_SECRET,
            )
        except ValueError as e:
            # Invalid JSON
            print(f"[webhook] Invalid payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            # Invalid signature
            print(f"[webhook] Invalid signature: {e}")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # Fallback: no verification (NOT recommended for production)
        print(
            "[webhook] WARNING: STRIPE_WEBHOOK_SECRET not set. "
            "Skipping signature verification."
        )
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception as e:
            print(f"[webhook] Could not parse JSON payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("type")
    data_obj = event.get("data", {}).get("object", {})

    print(f"[webhook] Received event: {event_type} (id={event.get('id')})")

    # -------------------------------------------------------------------
    # Subscription lifecycle logging (Option A – logging only)
    # -------------------------------------------------------------------
    if event_type == "customer.subscription.created":
        _log_subscription_event("created", data_obj)

    elif event_type == "customer.subscription.updated":
        _log_subscription_event("updated", data_obj)

    elif event_type == "customer.subscription.deleted":
        _log_subscription_event("deleted", data_obj)

    else:
        print(f"[webhook] Unhandled event type: {event_type}")

    # Stripe expects a 2xx response to consider the event delivered
    return {"received": True}


def _log_subscription_event(action: str, sub_obj: Dict[str, Any]) -> None:
    """
    Helper: log subscription details to stdout.

    You can later replace this with real DB writes.
    """
    sub_id = sub_obj.get("id")
    status = sub_obj.get("status")

    # Try to extract a price and email, if available
    items = sub_obj.get("items", {}).get("data", []) or []
    price_id = items[0]["price"]["id"] if items else None

    customer_email = (
        sub_obj.get("customer_email")
        or sub_obj.get("metadata", {}).get("email")
    )

    print(
        f"[subscription.{action}] "
        f"sub_id={sub_id} status={status} price_id={price_id} email={customer_email}"
    )
    # TODO: write to your database here if/when you add DB support
