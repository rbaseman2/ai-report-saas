# server/webhook.py
import os
import stripe
from fastapi import APIRouter, HTTPException, FastAPI, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# ---- Stripe exceptions (handle both layouts) -------------------------------
try:
    from stripe.error import StripeError, InvalidRequestError
except Exception:
    from stripe._error import StripeError, InvalidRequestError  # fallback for older pkgs

# ---- Required environment --------------------------------------------------
STRIPE_SECRET_KEY   = os.environ.get("STRIPE_SECRET_KEY", "")
PRICE_BASIC         = os.environ.get("PRICE_BASIC")
PRICE_PRO           = os.environ.get("PRICE_PRO")
PRICE_ENTERPRISE    = os.environ.get("PRICE_ENTERPRISE")
SUCCESS_URL         = os.environ.get("SUCCESS_URL")  # full https URL to your app
CANCEL_URL          = os.environ.get("CANCEL_URL")   # full https URL to your app
WEBHOOK_SECRET      = os.environ.get("STRIPE_WEBHOOK_SECRET", "")  # optional (for /stripe/webhook)

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set.")
if not SUCCESS_URL or not CANCEL_URL:
    raise RuntimeError("SUCCESS_URL and CANCEL_URL must be set to full https URLs.")

stripe.api_key = STRIPE_SECRET_KEY

# ---- FastAPI app + CORS ----------------------------------------------------
app = FastAPI()
router = APIRouter()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your Streamlit origin in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}

# ---- Plan → Price (server-authoritative) -----------------------------------
PLAN_TO_PRICE = {
    "basic": PRICE_BASIC,
    "pro":   PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}

class Body(BaseModel):
    plan: str  # "basic" | "pro" | "enterprise"

# ---- Create Checkout Session (subscription) --------------------------------
@router.post("/create-checkout-session")
def create_checkout_session(body: Body):
    price_id = PLAN_TO_PRICE.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    print(f">>> DEBUG stripe_version={getattr(stripe, '__version__', 'unknown')}", flush=True)
    print(f">>> DEBUG plan={body.plan}, price_id={price_id}", flush=True)

    # Build params (NO customer_creation here; illegal for mode='subscription')
    session_params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "allow_promotion_codes": True,  # lets you test with a 100% live promo code
        "success_url": SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}&status=success",
        "cancel_url":  CANCEL_URL  + "?status=cancelled",
        "automatic_tax": {"enabled": True},
        "billing_address_collection": "required",
        # Optional: tag the plan in subscription metadata
        "subscription_data": {"metadata": {"plan": body.plan}},
    }
    print(">>> DEBUG session_params keys:", sorted(session_params.keys()), flush=True)

    try:
        session = stripe.checkout.Session.create(**session_params)
        return {"url": session.url}
    except InvalidRequestError as e:
        msg = getattr(e, "user_message", str(e))
        print(f">>> STRIPE InvalidRequestError: {msg}", flush=True)
        raise HTTPException(status_code=400, detail=msg)
    except StripeError as e:
        msg = getattr(e, "user_message", "Stripe error")
        print(f">>> STRIPE StripeError: {msg}", flush=True)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        print(f">>> UNEXPECTED ERROR creating checkout session: {e}", flush=True)
        raise HTTPException(status_code=500, detail="Checkout creation failed")

# ---- Fetch Checkout Session details (used by the UI after success) ---------
@router.get("/checkout-session")
def get_checkout_session(session_id: str):
    try:
        sess = stripe.checkout.Session.retrieve(session_id, expand=["subscription", "customer"])
        sub  = getattr(sess, "subscription", None)
        email = getattr(getattr(sess, "customer_details", None), "email", None)
        plan_id = sub.items.data[0].plan.id if sub and sub.items and sub.items.data else None
        return {
            "id": sess.id,
            "customer_id": sess.customer,
            "subscription_id": sub.id if sub else None,
            "email": email,
            "plan_id": plan_id,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Unable to retrieve session: {e}")

# ---- Customer Portal (manage card/cancel) ----------------------------------
@router.post("/create-portal-session")
def create_portal_session(body: dict):
    customer_id = body.get("customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="customer_id is required")
    try:
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=SUCCESS_URL,  # or a dedicated /account page
        )
        return {"url": portal.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Unable to create portal session: {e}")

# ---- Optional: Stripe webhook to activate/deactivate entitlements ----------
@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=501, detail="Webhook not configured (missing STRIPE_WEBHOOK_SECRET).")
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook signature verification failed: {e}")

    et = event["type"]
    obj = event["data"]["object"]

    if et == "checkout.session.completed":
        # TODO: persist obj['customer'], obj['subscription'] and mark plan active for your user
        print(">>> WEBHOOK checkout.session.completed", obj.get("id"), flush=True)

    if et in ("customer.subscription.updated", "customer.subscription.deleted"):
        # TODO: update/cancel entitlements based on obj['status']
        print(f">>> WEBHOOK {et} status={obj.get('status')} id={obj.get('id')}", flush=True)

    return {"received": True}

# ---- Wire the router & startup logs ----------------------------------------
app.include_router(router)

@app.on_event("startup")
def _startup_logs():
    mode = "live" if STRIPE_SECRET_KEY.startswith("sk_live_") else "test"
    print(f">>> DEBUG using webhook file: {__file__}", flush=True)
    print(f">>> DEBUG STRIPE key mode: {mode}", flush=True)
    for k, v in {
        "PRICE_BASIC": PRICE_BASIC,
        "PRICE_PRO": PRICE_PRO,
        "PRICE_ENTERPRISE": PRICE_ENTERPRISE,
        "SUCCESS_URL": SUCCESS_URL,
        "CANCEL_URL": CANCEL_URL,
        "STRIPE_WEBHOOK_SECRET_set": bool(WEBHOOK_SECRET),
    }.items():
        prefix = (v[:12] if isinstance(v, str) and v else str(v))
        print(f">>> DEBUG {k}: {prefix}", flush=True)
