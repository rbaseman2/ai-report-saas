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

# Build a reverse lookup from price_id -> plan_key
PLAN_BY_PRICE: Dict[str, str] = {}
for plan_key, price_id in PRICE_BY_PLAN.items():
    if price_id:
        PLAN_BY_PRICE[price_id] = plan_key

# Frontend URL used for success & cancel redirect
FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "https://ai-report-saas.onrender.com",  # fallback to your Streamlit app
)

# ---------------------------------------------------------------------------
# FastAPI app setup
# ---------------------------------------------------------------------------

app = FastAPI(title="AI Report Backend - Stripe Webhook")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later if you want
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
# Subscription status lookup (used by Billing Step 1)
# ---------------------------------------------------------------------------

@app.get("/subscription-status")
async def subscription_status(email: str) -> Dict[str, Any]:
    """
    Look up the user's current subscription in Stripe by email.

    Returns:
    {
      "status": "active" | "trialing" | "past_due" | "canceled" | "none",
      "plan": "basic" | "pro" | "enterprise" | null
    }
    """
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    try:
        # Prefer Stripe's search API if available (matches metadata['email'])
        subs = None
        try:
            subs = stripe.Subscription.search(
                query=f"metadata['email']:'{email}'",
                limit=10,
            )
            sub_list = list(subs)  # materialize iterator
        except stripe.error.InvalidRequestError:
            # Fallback for accounts without Subscription.search enabled
            sub_list = []
            # You can adjust limit if you expect more subscriptions
            all_subs = stripe.Subscription.list(limit=50)
            for s in all_subs.auto_paging_iter():
                if (s.get("metadata") or {}).get("email") == email:
                    sub_list.append(s)

        # Find the most relevant (non-canceled) subscription, if any
        active_sub = None
        for s in sub_list:
            status = s.get("status")
            if status not in ("incomplete_expired", "canceled"):
                active_sub = s
                break

        if not active_sub:
            # No subscription found
            return {"status": "none", "plan": None}

        status = active_sub.get("status")
        items = active_sub.get("items", {}).get("data", []) or []
        price_id = items[0]["price"]["id"] if items else None
        plan_key = PLAN_BY_PRICE.get(price_id)

        print(
            f"[subscription-status] email={email} status={status} "
            f"price_id={price_id} plan={plan_key}"
        )

        return {
            "status": status,
            "plan": plan_key,
        }

    except stripe.error.StripeError as e:
        msg = getattr(e, "user_message", str(e))
        print(f"[subscription-status] Stripe error: {msg}")
        raise HTTPException(status_code=500, detail=f"Stripe error: {msg}")
    except Exception as e:
        print(f"[subscription-status] unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Error checking subscription")


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
            "allow_promotion_codes": True,
            "metadata": {
                "plan": plan_key,
                "email": body.email,
            },
        }

        if body.coupon:
            checkout_kwargs["discounts"] = [{"coupon": body.coupon}]

        session = stripe.checkout.Session.create(**checkout_kwargs)

        print(
            f"[create-checkout-session] email={body.email} plan={plan_key} "
            f"session_id={session.id}"
        )

        return {"checkout_url": session.url}

    except stripe.error.StripeError as e:
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
      - Does NOT touch any database (Option A – logging only).
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
        except ValueError as e:
            print(f"[webhook] Invalid payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            print(f"[webhook] Invalid signature: {e}")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
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

    if event_type == "customer.subscription.created":
        _log_subscription_event("created", data_obj)
    elif event_type == "customer.subscription.updated":
        _log_subscription_event("updated", data_obj)
    elif event_type == "customer.subscription.deleted":
        _log_subscription_event("deleted", data_obj)
    else:
        print(f"[webhook] Unhandled event type: {event_type}")

    return {"received": True}


def _log_subscription_event(action: str, sub_obj: Dict[str, Any]) -> None:
    """
    Helper: log subscription details to stdout.
    """
    sub_id = sub_obj.get("id")
    status = sub_obj.get("status")

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
