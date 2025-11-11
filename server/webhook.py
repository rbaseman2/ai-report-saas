# server/webhook.py
import os
import stripe
from fastapi import APIRouter, HTTPException, FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# --- Stripe exceptions (supports both layouts seen in your env) ---
try:
    from stripe.error import StripeError, InvalidRequestError
except Exception:
    from stripe._error import StripeError, InvalidRequestError  # fallback

# ---------- Read & validate environment ----------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
PRICE_BASIC = os.environ.get("PRICE_BASIC")
PRICE_PRO = os.environ.get("PRICE_PRO")
PRICE_ENTERPRISE = os.environ.get("PRICE_ENTERPRISE")
SUCCESS_URL = os.environ.get("SUCCESS_URL")
CANCEL_URL = os.environ.get("CANCEL_URL")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set.")
if not SUCCESS_URL or not CANCEL_URL:
    raise RuntimeError("SUCCESS_URL and CANCEL_URL must be set to full https URLs.")

stripe.api_key = STRIPE_SECRET_KEY

# ---------- FastAPI app + router ----------
app = FastAPI()
router = APIRouter()

# CORS (relax while testing; restrict in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}

# Server-authoritative plan → price mapping
PLAN_TO_PRICE = {
    "basic": PRICE_BASIC,
    "pro": PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}

class Body(BaseModel):
    plan: str  # "basic" | "pro" | "enterprise"

@router.post("/create-checkout-session")
def create_checkout_session(body: Body):
    price_id = PLAN_TO_PRICE.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    # Debug
    print(f">>> DEBUG stripe_version={getattr(stripe, '__version__', 'unknown')}", flush=True)
    print(f">>> DEBUG plan={body.plan}, price_id={price_id}", flush=True)

    # Build params (NO customer_creation here; it's only for mode='payment')
    session_params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "allow_promotion_codes": True,  # show "Add promotion code" box
        "success_url": SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": CANCEL_URL,
        "automatic_tax": {"enabled": True},
        "billing_address_collection": "required",
    }

    # Extra debug so logs prove exactly what's sent to Stripe
    print(">>> DEBUG session_params keys:", sorted(session_params.keys()), flush=True)
    print(">>> DEBUG contains customer_creation?:", "customer_creation" in session_params, flush=True)

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

# Wire the router
app.include_router(router)

# Startup diagnostics
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
    }.items():
        print(f">>> DEBUG {k} set={bool(v)} prefix={v[:12] if v else 'missing'}", flush=True)
