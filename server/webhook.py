# webhook.py
import os
import stripe
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# --- Stripe exceptions (compatible with all versions) ---
try:
    from stripe.error import StripeError, InvalidRequestError
except ModuleNotFoundError:
    from stripe._error import StripeError, InvalidRequestError

# --- Router setup ---
router = APIRouter()
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# --- Plan → Price mapping (server-side only) ---
PLAN_TO_PRICE = {
    "basic": os.environ.get("PRICE_BASIC"),
    "pro": os.environ.get("PRICE_PRO"),
    "enterprise": os.environ.get("PRICE_ENTERPRISE"),
}

# --- Request model ---
class Body(BaseModel):
    plan: str  # e.g., "basic", "pro", or "enterprise"

# --- Create Checkout Session ---
@router.post("/create-checkout-session")
def create_checkout_session(body: Body):
    price_id = PLAN_TO_PRICE.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    # Debug log (visible in Render logs)
    print(f">>> DEBUG plan={body.plan}, price_id={price_id}", flush=True)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=os.environ["SUCCESS_URL"] + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=os.environ["CANCEL_URL"],
            automatic_tax={"enabled": True},
        )
        return {"url": session.url}

    # Stripe-specific errors (bad price ID, wrong mode, etc.)
    except InvalidRequestError as e:
        raise HTTPException(status_code=400, detail=getattr(e, "user_message", str(e)))

    except StripeError as e:
        raise HTTPException(status_code=400, detail=getattr(e, "user_message", "Stripe error"))

    # Any other unhandled exceptions
    except Exception as e:
        print(f"Unexpected error creating checkout session: {e}", flush=True)
        raise HTTPException(status_code=500, detail="Checkout creation failed")
